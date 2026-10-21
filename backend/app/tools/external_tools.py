"""Lazy, turn-scoped MCP connections shared by framework tool adapters."""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os

import anyio
import httpx
from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.types import CallToolResult
from pydantic import RootModel

from app.errors import ServiceError
from app.runtime.tool_activity import record_tool_activity
from app.runtime.result_offload import offload_result
from app.tools.registry import ToolDefinition


@asynccontextmanager
async def open_mcp_session(config):
    async with AsyncExitStack() as stack:
        if config['type'] == 'stdio':
            # Preserve the SDK's subprocess environment and the current interpreter.
            parameters = StdioServerParameters(command=config['command'], args=config.get('args', []),
                                               env={**os.environ, **config.get('env', {})})
            streams = await stack.enter_async_context(stdio_client(parameters))
        elif config['type'] == 'http':
            client = await stack.enter_async_context(httpx.AsyncClient(headers=config.get('headers', {})))
            streams = await stack.enter_async_context(streamable_http_client(config['url'], http_client=client))
        else:
            streams = await stack.enter_async_context(sse_client(config['url'], headers=config.get('headers', {})))
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await session.initialize()
        yield session


class McpConnection:
    """One owner task keeps transport cancel scopes and session lifetime aligned."""
    def __init__(self, config, opener=None):
        self.config, self.opener = config, opener or open_mcp_session
        self.queue = asyncio.Queue()
        self.worker = None
        self.closed = False
        self.requests = set()

    async def _run(self):
        jobs = set()
        async with AsyncExitStack() as stack:
            session = None
            try:
                while True:
                    job = await self.queue.get()
                    if job is None:
                        break
                    method, arguments, future = job
                    if future.cancelled():
                        continue
                    try:
                        if session is None:
                            session = await stack.enter_async_context(self.opener(self.config))
                    except Exception:
                        if not future.done():
                            future.set_exception(ServiceError('MCP 工具服务暂时不可用，请稍后重试。', 502))
                        continue
                    if future.done():
                        continue
                    task = asyncio.create_task(self._dispatch(session, method, arguments, future))
                    jobs.add(task)
                    task.add_done_callback(jobs.discard)
                    future.add_done_callback(lambda done, running=task: running.cancel() if done.cancelled() else None)
            finally:
                for task in jobs:
                    task.cancel()
                if jobs:
                    await asyncio.gather(*jobs, return_exceptions=True)

    async def _dispatch(self, session, method, arguments, future):
        try:
            result = await getattr(session, method)(**arguments)
            if not future.done():
                future.set_result(result)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception:
            if not future.done():
                future.set_exception(ServiceError('MCP 工具服务暂时不可用，请稍后重试。', 502))

    async def request(self, method, **arguments):
        if self.closed:
            raise ServiceError('本轮 MCP 连接已关闭。', 409)
        if self.worker is None:
            self.worker = asyncio.create_task(self._run())
        future = asyncio.get_running_loop().create_future()
        self.requests.add(future)
        future.add_done_callback(self.requests.discard)
        await self.queue.put((method, arguments, future))
        return await future

    async def close(self):
        self.closed = True
        if self.worker is not None:
            for future in list(self.requests):
                future.cancel()
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None


class ExternalToolServer:
    def __init__(self, name, config, actions, audit, opener=None):
        self.name, self.actions, self.audit = name, set(actions), audit
        self.connection = McpConnection(config, opener)
        self.available = None
        self._discovery_lock = asyncio.Lock()

    async def definitions(self):
        async with self._discovery_lock:
            if self.available is None:
                available, cursor, seen = {}, None, set()
                while True:
                    result = await self.connection.request('list_tools', cursor=cursor)
                    for definition in result.tools:
                        if definition.name in self.actions:
                            available[definition.name] = definition
                    cursor = result.nextCursor
                    if not cursor:
                        break
                    if cursor in seen or len(seen) >= 20:
                        raise ServiceError('MCP 工具列表分页异常。', 502)
                    seen.add(cursor)
                self.available = available
        return [self._definition(item) for item in self.available.values()]

    async def invoke(self, name, arguments):
        qualified = f'mcp__{self.name}__{name}'
        response = await record_tool_activity(qualified, lambda: self._invoke(name, arguments))
        return await offload_result(qualified, response)

    async def _invoke(self, name, arguments):
        if name not in self.actions:
            return {'content': [{'type': 'text', 'text': '当前 Agent 未授权该 MCP 工具。'}], 'isError': True}

        async def call():
            await self.definitions()
            item = self.available.get(name)
            if item is None:
                raise ServiceError('MCP 工具不可用。', 502)
            validate(arguments, item.inputSchema)
            result = await self.connection.request('call_tool', name=name, arguments=arguments)
            return result.model_dump(mode='json', by_alias=True, exclude_none=True)
        try:
            return await self.audit.execute(self.name, name, arguments, call)
        except Exception:
            return {'content': [{'type': 'text', 'text': 'MCP 工具调用失败，请检查参数和服务后重试。'}], 'isError': True}

    def _definition(self, item):
        async def invoke(arguments):
            return await self.invoke(item.name, arguments)
        return ToolDefinition(item.name, RootModel[dict], item.description or item.name,
                              invoke, schema_override=item.inputSchema, validate_schema=False)

    def to_claude_sdk(self):
        server = Server(self.name, version='1.0.0')

        @server.list_tools()
        async def list_tools():
            await self.definitions()
            return list(self.available.values())

        @server.call_tool(validate_input=False)
        async def call_tool(name, arguments):
            return CallToolResult.model_validate(await self.invoke(name, arguments or {}))

        return {'type': 'sdk', 'name': self.name, 'instance': server}

    async def to_langchain(self):
        from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool

        owner = self
        class AuditedSession:
            async def call_tool(self, name, arguments, **kwargs):
                return CallToolResult.model_validate(await owner.invoke(name, arguments))

        await self.definitions()
        tools = []
        for definition in self.available.values():
            tool = convert_mcp_tool_to_langchain_tool(AuditedSession(), definition,
                server_name=self.name, handle_tool_errors=True)
            tools.append(tool.model_copy(update={'name': f'mcp__{self.name}__{definition.name}'}))
        return tools

    async def close(self):
        await self.connection.close()


@asynccontextmanager
async def external_tool_servers(options, allowed, audit):
    servers = []
    original = options.mcp_servers
    configured = dict(original)
    try:
        for name, config in original.items():
            if config.get('type') == 'sdk':
                continue
            prefix = f'mcp__{name}__'
            actions = [item[len(prefix):] for item in allowed if item.startswith(prefix)]
            proxy = ExternalToolServer(name, config, actions, audit)
            servers.append(proxy)
            configured[name] = proxy.to_claude_sdk()
        options.mcp_servers = configured
        yield
    finally:
        with anyio.CancelScope(shield=True):
            for server in reversed(servers):
                await server.close()
        options.mcp_servers = original

"""通过 MCP 初始化和工具列表协议读取服务能力，不执行工具。"""
import logging

import anyio
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from app.errors import ServiceError
from app.models.api import McpToolInfo


logger = logging.getLogger(__name__)


class McpDiscoveryService:
    async def list_tools(self, connection):
        try:
            with anyio.fail_after(15):
                async with httpx.AsyncClient(headers=connection.headers, timeout=10) as client:
                    if connection.transport == "http":
                        transport = streamable_http_client(str(connection.url), http_client=client)
                    else:
                        transport = sse_client(str(connection.url), headers=connection.headers, timeout=10)
                    async with transport as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            return await self._collect_tools(session)
        except TimeoutError as error:
            raise ServiceError("连接 MCP 服务超时，请检查地址和网络后重试。", 504) from error
        except Exception as error:
            # 不把服务返回的错误或认证请求头写到日志及页面。
            logger.warning("MCP 工具发现失败: server=%s", connection.name)
            raise ServiceError("无法读取 MCP 工具，请检查服务地址、连接方式和认证配置。", 502) from error

    async def _collect_tools(self, session):
        tools = {}
        cursor = None
        seen_cursors = set()
        while True:
            result = await session.list_tools(cursor=cursor)
            for item in result.tools:
                tools[item.name] = McpToolInfo(
                    name=item.name, description=item.description or "",
                    input_schema=item.inputSchema,
                )
            cursor = result.nextCursor
            if not cursor:
                return list(tools.values())
            if cursor in seen_cursors or len(seen_cursors) >= 20 or len(tools) > 1000:
                raise ValueError("MCP 工具列表分页异常")
            seen_cursors.add(cursor)

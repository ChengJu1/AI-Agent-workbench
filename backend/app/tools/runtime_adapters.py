"""Framework adapters register names/schemas and delegate to shared handlers."""
from app.runtime.tool_activity import record_tool_activity
from app.runtime.result_offload import offload_result
from app.tools.registry import ToolDefinition


def qualified_name(name, server_name):
    return f'mcp__{server_name}__{name}' if server_name else name


async def invoke_tool(definition, arguments, server_name=None):
    name = qualified_name(definition.name, server_name)
    response = await record_tool_activity(name, lambda: definition.invoke(arguments))
    return await offload_result(name, response)


def to_claude_tool(definition: ToolDefinition, server_name=None):
    from claude_agent_sdk import tool

    async def invoke(arguments):
        return await invoke_tool(definition, arguments, server_name)
    return tool(definition.name, definition.description, definition.schema)(invoke)


def to_claude_sdk(name, definitions):
    from mcp.server import Server
    from mcp.types import CallToolResult, Tool

    server = Server(name, version='1.0.0')
    registered = {definition.name: definition for definition in definitions}

    @server.list_tools()
    async def list_tools():
        return [Tool(name=item.name, description=item.description, inputSchema=item.schema)
                for item in definitions]

    @server.call_tool(validate_input=False)
    async def call_tool(action, arguments):
        definition = registered.get(action)
        if definition is None:
            return CallToolResult(content=[{'type': 'text', 'text': '当前 Agent 未授权该工具。'}], isError=True)
        response = await invoke_tool(definition, arguments or {}, name)
        return CallToolResult(content=response.get('content', []),
                              isError=bool(response.get('is_error') or response.get('isError')))

    return {'type': 'sdk', 'name': name, 'instance': server}


def to_langchain(definitions, server_name=None):
    from app.tools.langchain_adapter import SharedLangChainTool

    tools = []
    for definition in definitions:
        def bind(current):
            async def invoke(**arguments):
                result = await invoke_tool(current, arguments, server_name)
                return result, result
            return invoke
        tools.append(SharedLangChainTool.from_function(
            name=qualified_name(definition.name, server_name), description=definition.description,
            args_schema=definition.schema, coroutine=bind(definition), response_format='content_and_artifact',
        ))
    return tools

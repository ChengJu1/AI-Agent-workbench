"""Test-only MCP server over shared tool definitions, so tests can call platform tools the way a client does."""
from mcp.server import Server
from mcp.types import CallToolResult, Tool

from app.platform.service import SERVER_NAME
from app.tools.platform_tools import platform_definitions
from app.tools.runtime_adapters import invoke_tool


def definitions_server(name, definitions):
    server = Server(name, version='1.0.0')
    registered = {definition.name: definition for definition in definitions}

    @server.list_tools()
    async def list_tools():
        return [Tool(name=item.name, description=item.description, inputSchema=item.schema) for item in definitions]

    @server.call_tool(validate_input=False)
    async def call_tool(action, arguments):
        definition = registered.get(action)
        if definition is None:
            return CallToolResult(content=[{'type': 'text', 'text': '当前 Agent 未授权该工具。'}], isError=True)
        response = await invoke_tool(definition, arguments or {}, name)
        return CallToolResult(content=response.get('content', []),
                              isError=bool(response.get('is_error') or response.get('isError')))

    return {'type': 'sdk', 'name': name, 'instance': server}


def create_platform_server(platform, conversation_id, agent):
    definitions, allowed = platform_definitions(platform, conversation_id, agent)
    return definitions_server(SERVER_NAME, definitions), allowed

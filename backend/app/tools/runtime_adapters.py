"""Framework adapters only register names, schemas and the shared handler."""
from app.tools.registry import ToolDefinition


def to_claude_tool(definition: ToolDefinition):
    from claude_agent_sdk import tool

    return tool(definition.name, definition.description, definition.schema)(definition.invoke)


def to_claude_sdk(name, definitions):
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name=name, version='1.0.0',
                                 tools=[to_claude_tool(definition) for definition in definitions])


def to_langchain(definitions, server_name=None):
    # Installed with the Deep Agents runtime in stage 2, not needed by Claude.
    from langchain_core.tools import StructuredTool

    tools = []
    for definition in definitions:
        def bind(current):
            async def invoke(**arguments):
                return await current.invoke(arguments)
            return invoke
        tools.append(StructuredTool.from_function(
            name=f'mcp__{server_name}__{definition.name}' if server_name else definition.name, description=definition.description,
            args_schema=definition.schema, coroutine=bind(definition),
        ))
    return tools

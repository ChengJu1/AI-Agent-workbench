"""Framework adapters register names/schemas and delegate to shared handlers."""
from app.runtime.tool_activity import record_tool_activity
from app.runtime.result_offload import offload_result


def qualified_name(name, server_name):
    return f'mcp__{server_name}__{name}' if server_name else name


async def invoke_tool(definition, arguments, server_name=None):
    name = qualified_name(definition.name, server_name)
    response = await record_tool_activity(name, lambda: definition.invoke(arguments))
    return await offload_result(name, response)


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

"""One stdio MCP instance serves exactly one immutable package for one Agent."""
import argparse
import asyncio
import json

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from starlette.concurrency import run_in_threadpool

from app.capabilities.executor import PackageExecutor
from app.errors import ServiceError
from app.storage.database import Database


def make_server(executor):
    server = Server(f'generated-{executor.package_id}-v{executor.version}')

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=tool.name, description=tool.description,
                           inputSchema=tool.input_schema, outputSchema=tool.output_schema) for tool in executor.load().tools]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            result = await run_in_threadpool(executor.execute, name, arguments or {})
            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(result, ensure_ascii=False))],
                                        structuredContent=result)
        except ServiceError as error:
            return types.CallToolResult(content=[types.TextContent(type='text', text=str(error))], isError=True)
    return server


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--version', type=int, required=True)
    parser.add_argument('--agent', required=True)
    args = parser.parse_args()
    executor = PackageExecutor(Database(args.database), args.package, args.version, args.agent)
    server = make_server(executor)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())

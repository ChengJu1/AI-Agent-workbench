# 将 Agent Manifest 中的 MCP 配置转换为 Claude SDK 可使用的配置。
import sys

from app.models.agents import McpToolManifest, RemoteMcpToolManifest


class McpAdapter:
    def build(self, agent):
        mcp_server_dict = {}
        allowed_tools = []

        for tool in agent.tools:
            if not isinstance(tool, (McpToolManifest, RemoteMcpToolManifest)):
                continue

            if isinstance(tool, RemoteMcpToolManifest):
                mcp_dict = {"type": tool.transport, "url": str(tool.url)}
                if tool.headers:
                    mcp_dict["headers"] = dict(tool.headers)
            else:
                mcp_dict = {
                    "type": tool.transport, "command": sys.executable,
                    "args": ["-m", tool.module],
                }

            mcp_server_dict[tool.name] = mcp_dict

            for action in tool.actions:
                allowed_tool_name = (
                    f"mcp__{tool.name}__{action}"
                )
                allowed_tools.append(allowed_tool_name)

        return mcp_server_dict, allowed_tools


def build_external_tools(agent, database, adapter=None):
    from app.errors import ServiceError
    from app.storage.build_store import BuildStore

    servers, allowed = (adapter or McpAdapter()).build(agent)
    for reference in agent.generated_tools:
        package = BuildStore(database).package(reference.package_id, reference.version)
        name = f'generated_{reference.package_id}'
        if name in servers:
            raise ServiceError('MCP 连接名称与生成能力包冲突。', 409)
        servers[name] = {'type': 'stdio', 'command': sys.executable,
                         'args': ['-m', 'app.generated_mcp_server', '--database', str(database.path),
                                  '--package', reference.package_id, '--version', str(reference.version), '--agent', agent.id]}
        allowed.extend(f"mcp__{name}__{tool['name']}" for tool in package['plan']['tools'])
    return servers, allowed

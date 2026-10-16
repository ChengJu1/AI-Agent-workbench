# 将 Agent Manifest 中的 MCP 配置转换为 Claude SDK 可使用的配置。
import sys

from app.models.agents import McpToolManifest


class McpAdapter:
    def build(self, agent):
        mcp_server_dict = {}
        allowed_tools = []

        for tool in agent.tools:
            if not isinstance(tool, McpToolManifest):
                continue

            mcp_dict = {
                "type": tool.transport,
                "command": sys.executable,
                "args": [
                    "-m",
                    tool.module,
                ],
            }

            mcp_server_dict[tool.name] = mcp_dict

            for action in tool.actions:
                allowed_tool_name = (
                    f"mcp__{tool.name}__{action}"
                )
                allowed_tools.append(allowed_tool_name)

        return mcp_server_dict, allowed_tools

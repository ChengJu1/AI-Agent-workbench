# 定义 Agent Manifest 的配置结构，并使用 Pydantic 检查配置是否合法。
# 同时保存已经加载完 Prompt 和 Skill 的 Agent 运行配置。
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CliToolManifest(StrictModel):
    type: Literal["cli"]
    name: str
    actions: list[str] = Field(min_length=1)


class PermissionsManifest(StrictModel):
    dry_run_by_default: bool
    require_approval: list[str] = Field(default_factory=list)

class McpToolManifest(StrictModel):
    type: Literal["mcp"]
    name: str
    transport: Literal["stdio"]
    module: str
    actions: list[str] = Field(min_length=1)


class AgentManifest(StrictModel):
    id: str
    name: str
    description: str
    system_prompt: str
    skills: list[str] = Field(min_length=1)
    tools: list[CliToolManifest | McpToolManifest] = Field(min_length=1)
    permissions: PermissionsManifest

    @model_validator(mode="after")
    def validate_approval_actions(self):
        allowed_actions = set()

        for tool in self.tools:
            for action in tool.actions:
                allowed_actions.add(action)

        unknown_actions = []

        for action in self.permissions.require_approval:
            if action not in allowed_actions:
                unknown_actions.append(action)

        if unknown_actions:
            names = ", ".join(unknown_actions)
            raise ValueError(
                f"需要审批的 action 未出现在工具白名单中: {names}"
            )

        return self


class LoadedAgent(StrictModel):
    id: str
    name: str
    description: str
    system_prompt: str
    skills: list[str]
    tools: list[CliToolManifest | McpToolManifest]
    permissions: PermissionsManifest
    permission_mode: str = "default"
    max_turns: int = 50

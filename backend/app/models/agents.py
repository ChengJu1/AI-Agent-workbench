# 定义 Agent Manifest 的配置结构，并使用 Pydantic 检查配置是否合法。
# 同时保存已经加载完 Prompt 和 Skill 的 Agent 运行配置。
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CliToolManifest(StrictModel):
    type: Literal["cli"]
    name: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1)


class PermissionsManifest(StrictModel):
    dry_run_by_default: bool
    require_approval: list[str] = Field(default_factory=list)


class McpToolManifest(StrictModel):
    type: Literal["mcp"]
    name: str = Field(min_length=1)
    transport: Literal["stdio"]
    module: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1)


class AgentManifest(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    skills: list[str] = Field(min_length=1)
    tools: list[CliToolManifest | McpToolManifest] = Field(min_length=1)
    permissions: PermissionsManifest
    max_turns: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_approval_actions(self):
        allowed_actions = set()
        tool_names = set()

        for tool in self.tools:
            if tool.name in tool_names:
                raise ValueError(f"工具名称重复：{tool.name}")
            tool_names.add(tool.name)
            for action in tool.actions:
                if not action:
                    raise ValueError("工具 action 不能为空")
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

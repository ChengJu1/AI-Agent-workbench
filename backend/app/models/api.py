# 定义后端 API 请求和响应使用的数据结构。
# FastAPI 会使用这些模型校验前端传入的数据。
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.agents import RemoteMcpToolManifest
from app.platform.catalog import Capability
from app.models.evidence import KnowledgeEvidenceInfo
from app.models.skills import AgentSkillsRequest, SkillReference


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentInfo(BaseModel):
    platform_capabilities: list[Capability] = Field(default_factory=list)
    id: str
    name: str
    description: str
    archived: bool = False
    # 内置 Agent 只能归档，不能删除。
    deletable: bool = True


class ArchiveRequest(RequestModel):
    archived: bool


class TeamRequest(RequestModel):
    member_ids: list[str]
    mode: Literal['delegate', 'group_chat'] | None = None


class TeamInfo(BaseModel):
    mode: Literal['delegate', 'group_chat']
    members: list[AgentInfo]


class AgentKnowledgeRequest(RequestModel):
    knowledge_base_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=10
    )

    @model_validator(mode="after")
    def unique_bases(self):
        if len(self.knowledge_base_ids) != len(set(self.knowledge_base_ids)):
            raise ValueError("知识库不能重复选择")
        return self


class CreateAgentRequest(AgentKnowledgeRequest, AgentSkillsRequest):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    system_prompt: str = Field(min_length=1, max_length=50000)
    platform_capabilities: list[Capability] = Field(default_factory=list)
    tools: list[RemoteMcpToolManifest] = Field(default_factory=list, max_length=10)
    max_turns: int = Field(default=50, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def unique_servers(self):
        if not self.tools and not self.knowledge_base_ids and not self.skill_ids and not self.platform_capabilities:
            raise ValueError("请至少选择一个 Skill、知识库或 MCP 工具")
        names = [server.name for server in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("MCP 服务名称不能重复")
        if any(name in {"workbench_knowledge", "workbench_skills", "workbench_platform"} for name in names):
            raise ValueError("workbench_knowledge 和 workbench_skills 是工作台工具的保留连接名称")
        return self


class McpToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class CreateConversationRequest(RequestModel):
    agent_id: str = Field(min_length=1, max_length=100)


class CreateConversationResponse(BaseModel):
    conversation_id: str


class SendMessageRequest(RequestModel):
    content: str = Field(min_length=1, max_length=50000)
    # Image or scanned-PDF attachments of this conversation, sent to the model with the message.
    attachment_ids: list[Annotated[str, Field(pattern=r'^file_[0-9a-f]{32}$')]] = Field(default_factory=list, max_length=5)


class ContinueRequest(RequestModel):
    action_id: str = Field(min_length=1, max_length=64)


class ApprovalDecisionRequest(RequestModel):
    approved: bool = Field(strict=True)


class MessageInfo(BaseModel):
    usage: dict[str, Any] | None = None
    tool_activity: list[dict[str, Any]] | None = None
    role: str
    content: str
    knowledge: KnowledgeEvidenceInfo | None = None
    status: str | None = None
    skills: list[SkillReference] | None = None
    skill_mode: Literal["on_demand"] | None = None
    action_ids: list[str] | None = None
    attachments: list[dict[str, str]] | None = None
    delegated_by: str | None = None
    delegations: list[dict[str, Any]] | None = None

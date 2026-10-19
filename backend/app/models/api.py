# 定义后端 API 请求和响应使用的数据结构。
# FastAPI 会使用这些模型校验前端传入的数据。
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.agents import RemoteMcpToolManifest
from app.models.evidence import KnowledgeEvidenceInfo
from app.models.skills import AgentSkillsRequest, SkillReference


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str


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
    tools: list[RemoteMcpToolManifest] = Field(default_factory=list, max_length=10)
    max_turns: int = Field(default=50, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def unique_servers(self):
        if not self.tools and not self.knowledge_base_ids and not self.skill_ids:
            raise ValueError("请至少选择一个 Skill、知识库或 MCP 工具")
        names = [server.name for server in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("MCP 服务名称不能重复")
        if "workbench_knowledge" in names:
            raise ValueError("workbench_knowledge 是知识库工具的保留连接名称")
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


class ApprovalDecisionRequest(RequestModel):
    approved: bool = Field(strict=True)


class MessageInfo(BaseModel):
    role: str
    content: str
    knowledge: KnowledgeEvidenceInfo | None = None
    status: str | None = None
    skills: list[SkillReference] | None = None

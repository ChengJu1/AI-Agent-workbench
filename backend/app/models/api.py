# 定义后端 API 请求和响应使用的数据结构。
# FastAPI 会使用这些模型校验前端传入的数据。
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agents import RemoteMcpToolManifest


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str


class CreateAgentRequest(RequestModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    system_prompt: str = Field(min_length=1, max_length=50000)
    tools: list[RemoteMcpToolManifest] = Field(min_length=1, max_length=10)
    max_turns: int = Field(default=50, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def unique_servers(self):
        names = [server.name for server in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("MCP 服务名称不能重复")
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

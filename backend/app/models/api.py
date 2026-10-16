# 定义后端 API 请求和响应使用的数据结构。
# FastAPI 会使用这些模型校验前端传入的数据。
from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str


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

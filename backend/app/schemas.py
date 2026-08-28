# 定义后端 API 请求和响应使用的数据结构。
# FastAPI 会使用这些模型校验前端传入的数据。
from pydantic import BaseModel


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str


class CreateConversationRequest(BaseModel):
    agent_id: str


class CreateConversationResponse(BaseModel):
    conversation_id: str


class SendMessageRequest(BaseModel):
    content: str


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class MessageInfo(BaseModel):
    role: str
    content: str

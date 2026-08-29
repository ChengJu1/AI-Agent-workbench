from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str = Field(exclude=True)
    permission_mode: str = Field(default="default", exclude=True)
    max_turns: int = Field(default=3, exclude=True)


class CreateConversationRequest(BaseModel):
    agent_id: str


class CreateConversationResponse(BaseModel):
    conversation_id: str


class SendMessageRequest(BaseModel):
    content: str


class MessageInfo(BaseModel):
    role: str
    content: str

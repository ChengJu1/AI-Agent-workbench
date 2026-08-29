import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents import get_agent, list_agents
from app.schemas import (
    CreateConversationRequest,
    CreateConversationResponse,
    MessageInfo,
    SendMessageRequest,
)

from app.services.claude_runtime import ClaudeRuntimeService
from app.services.conversation_store import ConversationStore


app = FastAPI(title="AI Agent Workbench M1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ConversationStore()
runtime = ClaudeRuntimeService()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/agents")
def agents():
    return list_agents()


@app.post("/api/conversations", response_model=CreateConversationResponse)
def create_conversation(request: CreateConversationRequest):
    agent = get_agent(request.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    conversation_id = store.create(request.agent_id)
    return CreateConversationResponse(conversation_id=conversation_id)

@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageInfo])
def get_conversation_messages(conversation_id):
    if not store.exists(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )
    return store.get_messages(conversation_id)


@app.post("/api/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, request: SendMessageRequest):
    if not store.exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    agent_id = store.get_agent_id(conversation_id)
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    store.add_message(conversation_id, "user", request.content)

    saved_messages = store.get_messages(conversation_id)
    should_resume = any(
        message["role"] == "assistant"
        for message in saved_messages
    )

    async def event_stream():
        assistant_reply = ""
        try:
            async for chunk in runtime.stream_reply(
                conversation_id,
                agent,
                request.content,
                should_resume,
            ):
                assistant_reply += chunk
                payload = json.dumps(
                    {"type": "delta", "content": chunk},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            store.add_message(conversation_id, "assistant", assistant_reply)
            done_payload = json.dumps({"type": "done"}, ensure_ascii=False)
            yield f"data: {done_payload}\n\n"
        except Exception as error:
            error_payload = json.dumps(
                {"type": "error", "content": str(error)},
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

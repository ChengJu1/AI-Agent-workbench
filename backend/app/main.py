# 定义 FastAPI 应用及 M2 的会话、流式消息、审批和审计接口。
# 这里负责连接 Agent、Runtime、SQLite Store 和前端请求。
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents import get_agent, list_agents
from app.schemas import (
    CreateConversationRequest,
    CreateConversationResponse,
    ApprovalDecisionRequest,
    MessageInfo,
    SendMessageRequest,
)

from app.services.claude_runtime import ClaudeRuntimeService
from app.services.cli_adapter import CliAdapter
from app.services.conversation_store import ConversationStore
from app.services.tool_store import ToolStore


app = FastAPI(title="AI Agent Workbench M2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ConversationStore()
tool_store = ToolStore()
cli_adapter = CliAdapter()
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


@app.get(
    "/api/conversations/{conversation_id}/pending-actions"
)
def get_pending_actions(conversation_id):
    if not store.exists(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return tool_store.get_pending_actions(
        conversation_id
    )


@app.get(
    "/api/conversations/{conversation_id}/audit-logs"
)
def get_audit_logs(conversation_id):
    if not store.exists(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return tool_store.get_audit_logs(conversation_id)


@app.post(
    "/api/pending-actions/{pending_action_id}/decision"
)
def decide_pending_action(
    pending_action_id,
    request: ApprovalDecisionRequest,
):
    pending_action = tool_store.get_pending_action(
        pending_action_id
    )

    if pending_action is None:
        raise HTTPException(
            status_code=404,
            detail="Pending action not found",
        )

    if pending_action["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail="Pending action has already been handled",
        )

    if not request.approved:
        was_updated = tool_store.update_pending_action(
            pending_action_id,
            "cancelled",
        )

        if not was_updated:
            raise HTTPException(
                status_code=409,
                detail="Pending action has already been handled",
            )

        tool_store.add_audit_log(
            pending_action["conversation_id"],
            pending_action["agent_id"],
            pending_action["tool_name"],
            pending_action["action"],
            pending_action["params"],
            "cancelled",
        )

        feedback_message = (
            "本次工时提交已取消，没有执行提交操作。"
        )
        store.add_message(
            pending_action["conversation_id"],
            "assistant",
            feedback_message,
        )

        updated_action = tool_store.get_pending_action(
            pending_action_id
        )
        updated_action["message"] = feedback_message

        return updated_action

    was_claimed = tool_store.update_pending_action(
        pending_action_id,
        "executing",
    )

    if not was_claimed:
        raise HTTPException(
            status_code=409,
            detail="Pending action has already been handled",
        )

    try:
        agent = get_agent(pending_action["agent_id"])

        if agent is None:
            raise RuntimeError("Agent not found")

        result = cli_adapter.execute(
            agent,
            pending_action["tool_name"],
            pending_action["action"],
            pending_action["params"],
            approved=True,
        )

        tool_store.update_pending_action(
            pending_action_id,
            "approved",
            result=result,
            expected_status="executing",
        )

        tool_store.add_audit_log(
            pending_action["conversation_id"],
            pending_action["agent_id"],
            pending_action["tool_name"],
            pending_action["action"],
            pending_action["params"],
            "approved",
            result=result,
        )
    except Exception as error:
        error_result = {
            "error": str(error)
        }

        tool_store.update_pending_action(
            pending_action_id,
            "failed",
            result=error_result,
            expected_status="executing",
        )

        tool_store.add_audit_log(
            pending_action["conversation_id"],
            pending_action["agent_id"],
            pending_action["tool_name"],
            pending_action["action"],
            pending_action["params"],
            "failed",
            error=str(error),
        )

        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    submission_id = result.get(
        "submission_id",
        "",
    )
    feedback_message = (
        "工时已确认并提交成功。"
        f"提交编号：{submission_id}"
    )
    store.add_message(
        pending_action["conversation_id"],
        "assistant",
        feedback_message,
    )

    updated_action = tool_store.get_pending_action(
        pending_action_id
    )
    updated_action["message"] = feedback_message

    return updated_action


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
            async for runtime_event in runtime.stream_reply(
                conversation_id,
                agent,
                request.content,
                should_resume,
            ):
                if runtime_event["type"] == "delta":
                    assistant_reply += runtime_event[
                        "content"
                    ]

                payload = json.dumps(
                    runtime_event,
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            if assistant_reply:
                store.add_message(
                    conversation_id,
                    "assistant",
                    assistant_reply,
                )
            done_payload = json.dumps({"type": "done"}, ensure_ascii=False)
            yield f"data: {done_payload}\n\n"
        except Exception as error:
            error_payload = json.dumps(
                {"type": "error", "content": str(error)},
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

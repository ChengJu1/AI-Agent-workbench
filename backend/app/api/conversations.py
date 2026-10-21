"""提供会话、历史消息和 SSE 接口，保留原有 API 路径。"""
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_services
from app.api.streaming import ManagedStreamingResponse
from app.errors import ServiceError
from app.models.api import (
    CreateConversationRequest, CreateConversationResponse, MessageInfo, SendMessageRequest,
)


router = APIRouter(prefix="/api/conversations")


@router.post("", response_model=CreateConversationResponse)
def create_conversation(request: CreateConversationRequest, services=Depends(get_services)):
    if services.registry.get_agent(request.agent_id) is None:
        raise ServiceError("Agent not found", 404)
    return CreateConversationResponse(conversation_id=services.store.create(request.agent_id))


@router.get("/{conversation_id}/messages", response_model=list[MessageInfo], response_model_exclude_none=True)
def get_messages(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.store.get_messages(conversation_id)


@router.get("/{conversation_id}/pending-actions")
def get_pending_actions(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.tool_store.get_pending_actions(conversation_id)


@router.get("/{conversation_id}/actions")
def get_actions(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.tool_store.get_actions(conversation_id)


@router.get("/{conversation_id}/actions/{action_id}")
def get_action(conversation_id: str, action_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    action = services.tool_store.get_pending_action(action_id)
    if action is None or action['conversation_id'] != conversation_id:
        raise ServiceError('当前会话中没有这条操作。', 404)
    return action


@router.get("/{conversation_id}/audit-logs")
def get_audit_logs(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.tool_store.get_audit_logs(conversation_id)


@router.post("/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, request: SendMessageRequest,
                         services=Depends(get_services)):
    prepared = await run_in_threadpool(
        services.conversations.prepare, conversation_id, request.content
    )

    async def events():
        async with aclosing(services.conversations.stream(
            conversation_id, request.content, prepared
        )) as stream:
            async for event in stream:
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return ManagedStreamingResponse(
        events(), on_close=lambda: services.conversations.release(conversation_id, prepared),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

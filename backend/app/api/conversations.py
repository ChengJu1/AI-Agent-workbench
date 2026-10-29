"""提供会话、历史消息和 SSE 接口，保留原有 API 路径。"""
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_services
from app.api.streaming import ManagedStreamingResponse
from app.errors import ServiceError
from app.models.api import (
    ArchiveRequest, CreateConversationRequest, CreateConversationResponse, MessageInfo, SendMessageRequest, ContinueRequest,
)


router = APIRouter(prefix="/api/conversations")


@router.post("", response_model=CreateConversationResponse)
def create_conversation(request: CreateConversationRequest, services=Depends(get_services)):
    if services.registry.get_agent(request.agent_id) is None:
        raise ServiceError("Agent not found", 404)
    if request.agent_id in services.registry.archived_ids():
        raise ServiceError("该 Agent 已归档，请先恢复再新建会话。", 409)
    return CreateConversationResponse(conversation_id=services.conversations.create(request.agent_id))


@router.delete('/{conversation_id}')
def delete_conversation(conversation_id: str, services=Depends(get_services)):
    services.conversations.delete(conversation_id)
    return {'deleted': True}


@router.get('/archived')
def list_archived_conversations(services=Depends(get_services)):
    return services.store.list_archived()


@router.put('/{conversation_id}/archived')
def archive_conversation(conversation_id: str, request: ArchiveRequest, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    services.store.set_archived(conversation_id, request.archived)
    return {'archived': request.archived}


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
    if services.teams.parent(conversation_id) is not None:
        raise ServiceError("这是负责人委派给成员的子会话，只能查看和处理确认，请回到主会话继续。", 409)
    prepared = await run_in_threadpool(
        services.conversations.prepare, conversation_id, request.content, request.attachment_ids
    )
    return _reply_stream(services, conversation_id, request.content, prepared)


@router.post("/{conversation_id}/continue")
async def continue_after_actions(conversation_id: str, request: ContinueRequest,
                                 services=Depends(get_services)):
    """Resume once after the user decided this turn's actions; only the action id comes from the client."""
    prepared, notice = await run_in_threadpool(
        services.conversations.prepare_continuation, conversation_id, request.action_id
    )
    return _reply_stream(services, conversation_id, notice, prepared, {'type': 'platform_notice', 'content': notice})


def _reply_stream(services, conversation_id, content, prepared, first=None):
    async def events():
        if first is not None:
            yield "data: " + json.dumps(first, ensure_ascii=False) + "\n\n"
        async with aclosing(services.conversations.stream(
            conversation_id, content, prepared
        )) as stream:
            async for event in stream:
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return ManagedStreamingResponse(
        events(), on_close=lambda: services.conversations.release(conversation_id, prepared),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get('/{conversation_id}')
def get_conversation(conversation_id: str, services=Depends(get_services)):
    """会话的归属信息；子会话额外带上主会话和负责人，便于前端显示“由谁委派”。"""
    services.conversations.require_conversation(conversation_id)
    agent_id = services.store.get_agent_id(conversation_id)
    return {'id': conversation_id, 'agent_id': agent_id, 'agent_name': services.teams.agent_name(agent_id),
            'parent': services.teams.parent(conversation_id)}


@router.get('/{conversation_id}/delegations')
def list_delegations(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.teams.delegations(conversation_id)

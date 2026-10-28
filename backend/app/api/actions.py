"""接收人工确认或取消请求，具体提交流程由 ApprovalService 执行。"""
from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.models.api import ApprovalDecisionRequest


router = APIRouter(prefix="/api/pending-actions")


@router.post("/{action_id}/decision")
def decide(action_id: str, request: ApprovalDecisionRequest,
           services=Depends(get_services)):
    action = services.approvals.decide(action_id, request.approved, request.plan)
    if action["status"] in ("approved", "failed", "cancelled"):
        action["continuation_available"] = services.conversations.continuation_available(action)
    return action

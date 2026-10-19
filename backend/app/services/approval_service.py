"""组织人工确认流程；条件更新防止重复执行，最终结果使用事务保存。"""
import logging

from app.errors import ServiceError


logger = logging.getLogger(__name__)


class ApprovalService:
    def __init__(self, registry, tool_store, cli_adapter, platform=None):
        self.platform = platform
        self.registry = registry
        self.tool_store = tool_store
        self.cli_adapter = cli_adapter

    def decide(self, action_id, approved):
        action = self.tool_store.get_pending_action(action_id)
        if action is None:
            raise ServiceError("Pending action not found", 404)
        if action["status"] != "pending":
            raise ServiceError("Pending action has already been handled", 409)

        if not approved:
            message = "本次浏览器操作已取消，没有执行清单中的操作。" if action["tool_name"] == "workbench_platform" else "本次工时提交已取消，没有执行提交操作。"
            updated = self.tool_store.finish_action(
                action, "cancelled", message, expected_status="pending"
            )
            if not updated:
                raise ServiceError("Pending action has already been handled", 409)
            return self._response(action_id, message)

        agent = self.registry.get_agent(action["agent_id"])
        if agent is None:
            raise ServiceError("Agent not found", 404)
        if not self.tool_store.update_pending_action(action_id, "executing"):
            raise ServiceError("Pending action has already been handled", 409)

        try:
            if action["tool_name"] == "workbench_platform":
                if self.platform is None:
                    raise ServiceError("浏览器能力未初始化。", 503)
                result = self.platform.execute_approved(action)
            else:
                result = self.cli_adapter.execute(
                    agent, action["tool_name"], action["action"], action["params"], approved=True,
                )
        except Exception as error:
            logger.exception("确认操作执行失败: action_id=%s", action_id)
            message = str(error) if action["tool_name"] == "workbench_platform" and isinstance(error, ServiceError) else "工时提交失败，请稍后重试。"
            self.tool_store.finish_action(
                action, "failed", message,
                result={"error": message}, error=message,
            )
            raise ServiceError(message, 502) from error

        submission_id = result.get("submission_id", "")
        message = result.get("message", "已执行确认的浏览器操作，请核对页面回执。") if action["tool_name"] == "workbench_platform" else f"工时已确认并提交成功。提交编号：{submission_id}"
        try:
            updated = self.tool_store.finish_action(
                action, "approved", message, result=result
            )
            if not updated:
                raise RuntimeError("无法保存执行后的操作状态")
        except Exception as error:
            # 工具已经执行，不能伪装成执行失败，也不能自动再执行一次。
            logger.exception("提交结果保存失败: action_id=%s", action_id)
            raise ServiceError("提交结果暂未保存，请勿重复提交，请联系管理员核对。", 503) from error
        return self._response(action_id, message)

    def _response(self, action_id, message):
        action = self.tool_store.get_pending_action(action_id)
        action["message"] = message
        return action

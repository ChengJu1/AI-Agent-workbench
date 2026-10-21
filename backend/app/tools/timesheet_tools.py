"""按 Manifest 注册工时工具；提交只创建审批，普通操作调用受控 CLI。"""
import asyncio
import json

from app.tools.registry import ToolDefinition
from app.tools.runtime_adapters import to_claude_sdk, to_claude_tool

from app.models.agents import CliToolManifest
from app.models.tools import DraftTimesheetInput, QueryCalendarInput, SubmitTimesheetInput
from app.tools.cli_adapter import CliAdapter


TOOL_NAME = "timesheet_cli"
TOOL_DEFINITIONS = {
    "query_calendar": ("查询指定日期的模拟日程", QueryCalendarInput),
    "draft_timesheet": ("根据工作记录生成工时草稿", DraftTimesheetInput),
    "submit_timesheet": ("创建待确认的工时提交操作，不会直接提交", SubmitTimesheetInput),
}


class TimesheetToolSession:
    def __init__(self, server, allowed_tools, pending_actions):
        self.server = server
        self.allowed_tools = allowed_tools
        self.pending_actions = pending_actions


class TimesheetToolsService:
    def __init__(self, adapter=None, store=None):
        if store is None:
            raise ValueError("TimesheetToolsService 需要显式传入 ToolStore")
        self._adapter = adapter if adapter is not None else CliAdapter()
        self._store = store

    def _success_response(self, result):
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    def _error_response(self, conversation_id, agent, tool_name, action, arguments, error):
        self._store.add_audit_log(
            conversation_id, agent.id, tool_name, action, arguments,
            "failed", error=str(error),
        )
        return {"content": [{"type": "text", "text": str(error)}], "is_error": True}

    def _execute_safe_action(self, conversation_id, agent, tool_name, action, arguments):
        try:
            result = self._adapter.execute(agent, tool_name, action, arguments)
            self._store.add_audit_log(
                conversation_id, agent.id, tool_name, action, arguments,
                "success", result=result,
            )
            return self._success_response(result)
        except Exception as error:
            return self._error_response(
                conversation_id, agent, tool_name, action, arguments, error
            )

    def _create_pending_action(self, conversation_id, agent, tool_name, action,
                               arguments, pending_actions):
        try:
            validated = self._adapter.validate(agent, tool_name, action, arguments)
            # 存储层在同一个事务中创建操作和 pending 审计，失败时一起回滚。
            action_id = self._store.create_pending_action(
                conversation_id, agent.id, tool_name, action, validated
            )
            pending_actions.append(self._store.get_pending_action(action_id))
            return self._success_response({
                "status": "approval_required", "pending_action_id": action_id,
                "message": "提交工时前需要用户确认",
            })
        except Exception as error:
            return self._error_response(
                conversation_id, agent, tool_name, action, arguments, error
            )

    def _definition(self, conversation_id, agent, action, pending_actions):
        description, input_model = TOOL_DEFINITIONS[action]

        async def handle(arguments):
            if action == "submit_timesheet":
                return await asyncio.to_thread(
                    self._create_pending_action, conversation_id, agent, TOOL_NAME,
                    action, arguments, pending_actions,
                )
            return await asyncio.to_thread(
                self._execute_safe_action, conversation_id, agent, TOOL_NAME, action, arguments
            )

        return ToolDefinition(action, input_model, description, handle)

    def _register_tool(self, conversation_id, agent, action, pending_actions):
        return to_claude_tool(self._definition(conversation_id, agent, action, pending_actions))

    def definitions(self, conversation_id, agent):
        actions = []
        for configured in agent.tools:
            if isinstance(configured, CliToolManifest) and configured.name == TOOL_NAME:
                actions = list(dict.fromkeys(configured.actions))
                break
        unknown = set(actions) - TOOL_DEFINITIONS.keys()
        if unknown:
            raise ValueError(f"不支持的工时工具 action：{', '.join(sorted(unknown))}")

        pending_actions = []
        definitions = [self._definition(conversation_id, agent, action, pending_actions) for action in actions]
        return definitions, pending_actions

    def create_session(self, conversation_id, agent):
        definitions, pending_actions = self.definitions(conversation_id, agent)
        return TimesheetToolSession(
            to_claude_sdk(TOOL_NAME, definitions),
            [f'mcp__{TOOL_NAME}__{definition.name}' for definition in definitions], pending_actions,
        )

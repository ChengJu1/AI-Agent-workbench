# 把三个工时 CLI action 注册成 Claude SDK 可以调用的工具。
# 普通操作会立即执行，提交操作只创建等待人工确认的 Pending Action。
import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from app.services.cli_adapter import CliAdapter
from app.services.tool_store import ToolStore
from app.tool_schemas import (
    DraftTimesheetInput,
    QueryCalendarInput,
    SubmitTimesheetInput,
)
"""
1. 把三个 action 注册成 Claude 可以调用的工具
2. 接收模型传来的参数
3. 调用 CLI Adapter
4. 记录日志或创建 Pending Action
"""

class TimesheetToolSession:
    def __init__(self, server, allowed_tools, pending_actions):
        self.server = server
        self.allowed_tools = allowed_tools
        self.pending_actions = pending_actions


class TimesheetToolsService:
    def __init__(self, adapter=None, store=None):
        if adapter is None:
            adapter = CliAdapter()

        if store is None:
            store = ToolStore()

        self._adapter = adapter
        self._store = store

    def _success_response(self, result):
        text = json.dumps(
            result,
            ensure_ascii=False,
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ]
        }

    def _error_response(self, error):
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(error),
                }
            ],
            "is_error": True,
        }

    def _execute_safe_action(
        self,
        conversation_id,
        agent,
        tool_name,
        action,
        arguments,
    ):
        try:
            result = self._adapter.execute(
                agent,
                tool_name,
                action,
                arguments,
            )

            self._store.add_audit_log(
                conversation_id,
                agent.id,
                tool_name,
                action,
                arguments,
                "success",
                result=result,
            )

            return self._success_response(result)
        except Exception as error:
            self._store.add_audit_log(
                conversation_id,
                agent.id,
                tool_name,
                action,
                arguments,
                "failed",
                error=str(error),
            )

            return self._error_response(error)

    def _create_pending_action(
        self,
        conversation_id,
        agent,
        tool_name,
        action,
        arguments,
        pending_actions,
    ):
        try:
            validated_arguments = self._adapter.validate(
                agent,
                tool_name,
                action,
                arguments,
            )

            pending_action_id = (
                self._store.create_pending_action(
                    conversation_id,
                    agent.id,
                    tool_name,
                    action,
                    validated_arguments,
                )
            )

            pending_action = self._store.get_pending_action(
                pending_action_id
            )
            pending_actions.append(pending_action)

            audit_result = {
                "pending_action_id": pending_action_id
            }

            self._store.add_audit_log(
                conversation_id,
                agent.id,
                tool_name,
                action,
                validated_arguments,
                "pending",
                result=audit_result,
            )

            tool_result = {
                "status": "approval_required",
                "pending_action_id": pending_action_id,
                "message": "提交工时前需要用户确认",
            }

            return self._success_response(tool_result)
        except Exception as error:
            self._store.add_audit_log(
                conversation_id,
                agent.id,
                tool_name,
                action,
                arguments,
                "failed",
                error=str(error),
            )

            return self._error_response(error)

    def create_session(self, conversation_id, agent):
        tool_name = "timesheet_cli"
        pending_actions = []

        query_schema = (
            QueryCalendarInput.model_json_schema()
        )
        draft_schema = (
            DraftTimesheetInput.model_json_schema()
        )
        submit_schema = (
            SubmitTimesheetInput.model_json_schema()
        )

        @tool(
            "query_calendar",
            "查询指定日期的模拟日程",
            query_schema,
        )
        async def query_calendar_tool(arguments):
            return self._execute_safe_action(
                conversation_id,
                agent,
                tool_name,
                "query_calendar",
                arguments,
            )

        @tool(
            "draft_timesheet",
            "根据工作记录生成工时草稿",
            draft_schema,
        )
        async def draft_timesheet_tool(arguments):
            return self._execute_safe_action(
                conversation_id,
                agent,
                tool_name,
                "draft_timesheet",
                arguments,
            )

        @tool(
            "submit_timesheet",
            "创建待确认的工时提交操作，不会直接提交",
            submit_schema,
        )
        async def submit_timesheet_tool(arguments):
            return self._create_pending_action(
                conversation_id,
                agent,
                tool_name,
                "submit_timesheet",
                arguments,
                pending_actions,
            )

        tools = [
            query_calendar_tool,
            draft_timesheet_tool,
            submit_timesheet_tool,
        ]

        server = create_sdk_mcp_server(
            name=tool_name,
            version="1.0.0",
            tools=tools,
        )

        allowed_tools = []

        for configured_tool in agent.tools:
            if configured_tool.name != tool_name:
                continue

            for action in configured_tool.actions:
                sdk_tool_name = (
                    f"mcp__{tool_name}__{action}"
                )
                allowed_tools.append(sdk_tool_name)

        return TimesheetToolSession(
            server,
            allowed_tools,
            pending_actions,
        )

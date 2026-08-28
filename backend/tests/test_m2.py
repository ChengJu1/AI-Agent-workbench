# 验证 M2 的 CLI 白名单、SDK 工具、审批接口、审计日志和 SSE 事件。
# 所有数据库测试都使用临时文件，不会写入正式 workbench.db。
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from mcp.shared.memory import (
    create_connected_server_and_client_session,
)


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIRECTORY))


from app import main
from app.agents import get_agent
from app.services.cli_adapter import CliAdapter
from app.services.conversation_store import ConversationStore
from app.services.timesheet_tools import TimesheetToolsService
from app.services.tool_store import ToolStore


class FakeRuntime:
    def __init__(self, pending_action):
        self._pending_action = pending_action

    async def stream_reply(
        self,
        conversation_id,
        agent,
        user_message,
        should_resume,
    ):
        yield {
            "type": "delta",
            "content": "测试回复",
        }

        if self._pending_action is not None:
            yield {
                "type": "approval_required",
                "action": self._pending_action,
            }


class M2TestCase(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        database_path = (
            Path(self._temporary_directory.name)
            / "test.db"
        )

        self.conversation_store = (
            ConversationStore.__new__(ConversationStore)
        )
        self.conversation_store._database_path = (
            database_path
        )
        self.conversation_store._initialize_database()

        self.tool_store = ToolStore.__new__(ToolStore)
        self.tool_store._database_path = database_path
        self.tool_store._initialize_database()

        self.agent = get_agent("timesheet_assistant")
        self.conversation_id = (
            self.conversation_store.create(
                self.agent.id
            )
        )
        self.adapter = CliAdapter()

        main.store = self.conversation_store
        main.tool_store = self.tool_store
        main.cli_adapter = self.adapter

        self.client = TestClient(main.app)

    def tearDown(self):
        self._temporary_directory.cleanup()

    def _draft_payload(self):
        return {
            "draft": {
                "records": [
                    {
                        "date": "2026-08-27",
                        "task": "项目晨会",
                        "hours": 1.0,
                        "note": "团队同步",
                    }
                ],
                "total_hours": 1.0,
            }
        }

    def _create_pending_action(self):
        service = TimesheetToolsService(
            adapter=self.adapter,
            store=self.tool_store,
        )
        pending_actions = []

        response = service._create_pending_action(
            self.conversation_id,
            self.agent,
            "timesheet_cli",
            "submit_timesheet",
            self._draft_payload(),
            pending_actions,
        )

        self.assertNotIn("is_error", response)
        self.assertEqual(len(pending_actions), 1)

        return pending_actions[0]

    def test_cli_adapter_blocks_unapproved_submit(self):
        with self.assertRaises(PermissionError):
            self.adapter.execute(
                self.agent,
                "timesheet_cli",
                "submit_timesheet",
                self._draft_payload(),
            )

    def test_cli_adapter_executes_safe_action(self):
        result = self.adapter.execute(
            self.agent,
            "timesheet_cli",
            "query_calendar",
            {"date": "2026-08-27"},
        )

        self.assertEqual(result["total_hours"], 4.5)

    def test_sdk_tool_server_calls_cli_actions(self):
        service = TimesheetToolsService(
            adapter=self.adapter,
            store=self.tool_store,
        )
        tool_session = service.create_session(
            self.conversation_id,
            self.agent,
        )

        async def call_tools():
            server = tool_session.server["instance"]

            async with (
                create_connected_server_and_client_session(
                    server
                )
            ) as client:
                tools_result = await client.list_tools()
                tool_names = []

                for available_tool in tools_result.tools:
                    tool_names.append(available_tool.name)

                query_result = await client.call_tool(
                    "query_calendar",
                    {"date": "2026-08-27"},
                )
                submit_result = await client.call_tool(
                    "submit_timesheet",
                    self._draft_payload(),
                )

                return (
                    tool_names,
                    query_result,
                    submit_result,
                )

        results = asyncio.run(call_tools())
        tool_names = results[0]
        query_result = results[1]
        submit_result = results[2]

        self.assertIn("query_calendar", tool_names)
        self.assertIn("draft_timesheet", tool_names)
        self.assertIn("submit_timesheet", tool_names)
        self.assertFalse(query_result.isError)
        self.assertFalse(submit_result.isError)
        self.assertEqual(
            len(tool_session.pending_actions),
            1,
        )

    def test_approve_pending_action(self):
        pending_action = self._create_pending_action()

        response = self.client.post(
            (
                "/api/pending-actions/"
                + pending_action["id"]
                + "/decision"
            ),
            json={"approved": True},
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(
            response_data["status"],
            "approved",
        )
        self.assertEqual(
            response_data["result"]["status"],
            "submitted",
        )
        self.assertIn(
            "工时已确认并提交成功",
            response_data["message"],
        )

        pending_actions = self.tool_store.get_pending_actions(
            self.conversation_id
        )
        self.assertEqual(pending_actions, [])

        messages = self.conversation_store.get_messages(
            self.conversation_id
        )
        self.assertIn(
            "工时已确认并提交成功",
            messages[-1]["content"],
        )

        second_response = self.client.post(
            (
                "/api/pending-actions/"
                + pending_action["id"]
                + "/decision"
            ),
            json={"approved": True},
        )
        self.assertEqual(second_response.status_code, 409)

    def test_cancel_pending_action(self):
        pending_action = self._create_pending_action()

        response = self.client.post(
            (
                "/api/pending-actions/"
                + pending_action["id"]
                + "/decision"
            ),
            json={"approved": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["status"],
            "cancelled",
        )
        self.assertIn(
            "本次工时提交已取消",
            response.json()["message"],
        )

        pending_actions = self.tool_store.get_pending_actions(
            self.conversation_id
        )
        self.assertEqual(pending_actions, [])

    def test_audit_log_api(self):
        pending_action = self._create_pending_action()

        self.client.post(
            (
                "/api/pending-actions/"
                + pending_action["id"]
                + "/decision"
            ),
            json={"approved": False},
        )

        response = self.client.get(
            (
                "/api/conversations/"
                + self.conversation_id
                + "/audit-logs"
            )
        )

        self.assertEqual(response.status_code, 200)

        statuses = []

        for audit_log in response.json():
            statuses.append(audit_log["status"])

        self.assertIn("pending", statuses)
        self.assertIn("cancelled", statuses)

    def test_stream_contains_approval_event(self):
        pending_action = self._create_pending_action()
        main.runtime = FakeRuntime(pending_action)

        response = self.client.post(
            (
                "/api/conversations/"
                + self.conversation_id
                + "/messages/stream"
            ),
            json={"content": "提交今天的工时"},
        )

        self.assertEqual(response.status_code, 200)

        events = []

        for block in response.text.split("\n\n"):
            if not block.startswith("data: "):
                continue

            event = json.loads(block[6:])
            events.append(event)

        event_types = []

        for event in events:
            event_types.append(event["type"])

        self.assertIn("delta", event_types)
        self.assertIn("approval_required", event_types)
        self.assertIn("done", event_types)


if __name__ == "__main__":
    unittest.main()

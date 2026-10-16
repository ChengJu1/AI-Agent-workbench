"""验证重构后的初始化边界、旧数据兼容、审批事务和异常流式处理。"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import anyio
from fastapi.testclient import TestClient
from pydantic import ValidationError


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.application import create_app
from app.api.conversations import stream_message
from app.config import Settings
from app.container import Services
from app.errors import ServiceError
from app.models.tools import QueryCalendarInput, TimesheetRecord
from app.models.api import SendMessageRequest
from app.services.agent_registry import AgentRegistry
from app.services.approval_service import ApprovalService
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.policy_store import PolicyStore
from app.storage.tool_store import ToolStore
from app.tools.cli_adapter import CliAdapter
from app.tools.timesheet_tools import TimesheetToolsService


class PartialFailureRuntime:
    async def stream_reply(self, *args, **kwargs):
        yield {"type": "delta", "content": "已经收到的部分回复"}
        raise RuntimeError("private-api-token-and-file-path")


class ArchitectureTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workbench tests ")
        self.directory = Path(self.temporary.name)
        self.database = Database(self.directory / "test.db")
        self.database.initialize()
        self.store = ConversationStore(self.database)
        self.tools = ToolStore(self.database)
        self.registry = AgentRegistry()
        self.conversation_id = self.store.create("timesheet_assistant")

    def tearDown(self):
        self.temporary.cleanup()

    def pending_action(self):
        action_id = self.tools.create_pending_action(
            self.conversation_id, "timesheet_assistant", "timesheet_cli",
            "submit_timesheet", {"draft": {"records": [], "total_hours": 1}},
        )
        return self.tools.get_pending_action(action_id)

    def block_audit_writes(self):
        with self.database.connection() as connection:
            connection.execute(
                "CREATE TRIGGER reject_audit BEFORE INSERT ON tool_audit_logs "
                "BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
            )

    def test_importing_application_does_not_create_database(self):
        path = self.directory / "must-not-be-created.db"
        env = os.environ.copy()
        env["WORKBENCH_DATABASE_PATH"] = str(path)
        result = subprocess.run(
            [sys.executable, "-c", "from app.main import app; print(app.state.services)"],
            cwd=BACKEND_DIRECTORY, env=env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")
        self.assertFalse(path.exists())

    def test_connection_to_wrong_path_does_not_create_empty_database(self):
        path = self.directory / "wrong.db"
        database = Database(path)
        with self.assertRaises(sqlite3.OperationalError):
            with database.connection():
                pass
        self.assertFalse(path.exists())

    def test_startup_initializes_explicit_database_path(self):
        path = self.directory / "startup.db"
        app = create_app(settings=Settings(database_path=path))
        self.assertFalse(path.exists())
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
        self.assertTrue(path.exists())

    def test_legacy_audit_schema_is_upgraded_without_losing_messages(self):
        self.store.add_message(self.conversation_id, "user", "保留旧消息")
        with self.database.connection() as connection:
            connection.execute("ALTER TABLE tool_audit_logs DROP COLUMN tool_type")
        self.database.initialize()
        self.database.initialize()
        self.tools.add_audit_log(
            self.conversation_id, "timesheet_assistant", "timesheet_cli",
            "query_calendar", {}, "success",
        )
        self.assertEqual(self.store.get_messages(self.conversation_id)[0]["content"], "保留旧消息")
        self.assertEqual(self.tools.get_audit_logs(self.conversation_id)[0]["tool_type"], "cli")

    def test_cancel_rolls_back_state_if_audit_cannot_be_saved(self):
        action = self.pending_action()
        self.block_audit_writes()
        with self.assertRaises(sqlite3.IntegrityError):
            self.tools.finish_action(
                action, "cancelled", "已取消", expected_status="pending"
            )
        self.assertEqual(self.tools.get_pending_action(action["id"])["status"], "pending")
        self.assertEqual(self.store.get_messages(self.conversation_id), [])

    def test_pending_creation_rolls_back_if_audit_cannot_be_saved(self):
        self.block_audit_writes()
        with self.assertRaises(sqlite3.IntegrityError):
            self.pending_action()
        self.assertEqual(self.tools.get_pending_actions(self.conversation_id), [])

    def test_pending_creation_records_exactly_one_audit(self):
        action = self.pending_action()
        logs = self.tools.get_audit_logs(self.conversation_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["status"], "pending")
        self.assertEqual(logs[0]["result"], {"pending_action_id": action["id"]})

    def test_sdk_server_exposes_only_manifest_actions(self):
        from mcp.shared.memory import create_connected_server_and_client_session

        agent = self.registry.get_agent("timesheet_assistant").model_copy(deep=True)
        agent.tools[0].actions = ["query_calendar"]
        service = TimesheetToolsService(store=self.tools)
        session = service.create_session(self.conversation_id, agent)

        async def list_tools():
            async with create_connected_server_and_client_session(
                session.server["instance"]
            ) as client:
                return await client.list_tools()

        result = asyncio.run(list_tools())
        self.assertEqual([tool.name for tool in result.tools], ["query_calendar"])
        self.assertEqual(session.allowed_tools, ["mcp__timesheet_cli__query_calendar"])

    def test_concurrent_confirmations_execute_tool_only_once(self):
        action = self.pending_action()
        started = threading.Event()
        finish = threading.Event()

        class BlockingAdapter:
            calls = 0

            def execute(self, *args, **kwargs):
                self.calls += 1
                started.set()
                if not finish.wait(5):
                    raise RuntimeError("test timed out")
                return {"status": "submitted", "submission_id": "once-only"}

        adapter = BlockingAdapter()
        service = ApprovalService(self.registry, self.tools, adapter)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.decide, action["id"], True)
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaises(ServiceError) as raised:
                    service.decide(action["id"], True)
                self.assertEqual(raised.exception.status_code, 409)
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=5)["status"], "approved")
        self.assertEqual(adapter.calls, 1)

    def test_successful_tool_is_not_reexecuted_after_result_save_failure(self):
        action = self.pending_action()
        adapter = unittest.mock.Mock()
        adapter.execute.return_value = {"submission_id": "already-executed"}
        service = ApprovalService(self.registry, self.tools, adapter)
        self.block_audit_writes()
        with patch("app.services.approval_service.logger.exception"):
            with self.assertRaises(ServiceError) as raised:
                service.decide(action["id"], True)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(self.tools.get_pending_action(action["id"])["status"], "executing")
        with self.assertRaises(ServiceError):
            service.decide(action["id"], True)
        adapter.execute.assert_called_once()

    def test_partial_stream_is_saved_and_internal_error_is_hidden(self):
        services = Services(
            self.registry, self.store, self.tools, CliAdapter(), PartialFailureRuntime()
        )
        with TestClient(create_app(services=services)) as client:
            with patch("app.services.conversation_service.logger.exception"):
                response = client.post(
                    f"/api/conversations/{self.conversation_id}/messages/stream",
                    json={"content": "请回复"},
                )
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn("private-api-token", response.text)
        self.assertEqual(
            self.store.get_messages(self.conversation_id)[-1]["content"],
            "已经收到的部分回复",
        )
        self.assertNotIn(self.conversation_id, services.conversations._active)

    def test_same_conversation_rejects_overlapping_model_requests(self):
        services = Services(
            self.registry, self.store, self.tools, CliAdapter(), PartialFailureRuntime()
        )
        service = services.conversations
        prepared = service.prepare(self.conversation_id, "第一条")
        with self.assertRaises(ServiceError) as raised:
            service.prepare(self.conversation_id, "第二条")
        self.assertEqual(raised.exception.status_code, 409)

        async def finish_request():
            with patch("app.services.conversation_service.logger.exception"):
                async for _ in service.stream(self.conversation_id, "第一条", prepared):
                    pass

        asyncio.run(finish_request())
        self.assertEqual(len(self.store.get_messages(self.conversation_id)), 2)

    def test_disconnect_releases_conversation_and_closes_runtime(self):
        for disconnect_on in ["http.response.start", "http.response.body"]:
            with self.subTest(disconnect_on=disconnect_on):
                closed = []

                class ClosingRuntime:
                    async def stream_reply(self, *args, **kwargs):
                        try:
                            yield {"type": "delta", "content": "部分回复"}
                        finally:
                            closed.append(True)

                services = Services(
                    self.registry, self.store, self.tools, CliAdapter(), ClosingRuntime()
                )

                async def run():
                    from starlette.requests import ClientDisconnect

                    async def send(message):
                        if message["type"] == disconnect_on:
                            raise OSError("client disconnected")

                    async def receive():
                        return {"type": "http.disconnect"}

                    response = await stream_message(
                        self.conversation_id, SendMessageRequest(content="请回复"), services
                    )
                    with self.assertRaises(ClientDisconnect):
                        await response(
                            {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send
                        )
                    self.assertNotIn(self.conversation_id, services.conversations._active)
                    if disconnect_on == "http.response.body":
                        self.assertEqual(closed, [True])
                        self.assertEqual(self.store.get_messages(self.conversation_id)[-1]["content"], "部分回复")

                asyncio.run(run())

    def test_old_response_cleanup_cannot_release_a_new_reply(self):
        services = Services(
            self.registry, self.store, self.tools, CliAdapter(), PartialFailureRuntime()
        )
        service = services.conversations
        first = service.prepare(self.conversation_id, "第一条")
        service.release(self.conversation_id, first)
        second = service.prepare(self.conversation_id, "第二条")
        service.release(self.conversation_id, first)
        with self.assertRaises(ServiceError):
            service.prepare(self.conversation_id, "第三条")
        service.release(self.conversation_id, second)

    def test_disconnect_via_receive_closes_runtime_in_its_original_task(self):
        closed = []

        class ScopedRuntime:
            async def stream_reply(self, *args, **kwargs):
                # SDK 会跨 yield 保留取消作用域，必须在创建它的任务中关闭。
                with anyio.CancelScope():
                    try:
                        yield {"type": "delta", "content": "部分回复"}
                    finally:
                        closed.append(True)

        services = Services(self.registry, self.store, self.tools, CliAdapter(), ScopedRuntime())

        async def run():
            sent = anyio.Event()

            async def send(message):
                if message["type"] == "http.response.body":
                    sent.set()
                    await anyio.sleep_forever()

            async def receive():
                await sent.wait()
                return {"type": "http.disconnect"}

            response = await stream_message(
                self.conversation_id, SendMessageRequest(content="请回复"), services
            )
            with anyio.fail_after(5):
                await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
            self.assertEqual(closed, [True])
            self.assertNotIn(self.conversation_id, services.conversations._active)

        asyncio.run(run())

    def test_blank_messages_and_non_boolean_approvals_are_rejected(self):
        services = Services(
            self.registry, self.store, self.tools, CliAdapter(), PartialFailureRuntime()
        )
        with TestClient(create_app(services=services)) as client:
            response = client.post(
                f"/api/conversations/{self.conversation_id}/messages/stream",
                json={"content": "   "},
            )
            self.assertEqual(response.status_code, 422)
            response = client.post("/api/pending-actions/unknown/decision", json={"approved": "yes"})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.get_messages(self.conversation_id), [])

    def test_tool_inputs_reject_impossible_dates_and_invalid_hours(self):
        with self.assertRaises(ValidationError):
            QueryCalendarInput(date="2026-02-30")
        for hours in [True, float("inf"), float("nan"), 0, -1, 0.25]:
            with self.subTest(hours=hours):
                with self.assertRaises(ValidationError):
                    TimesheetRecord(date="2026-08-27", task="工作", hours=hours)

    def test_policy_cache_reuses_unchanged_files_and_refreshes_after_edit(self):
        directory = self.directory / "policies"
        directory.mkdir()
        path = directory / "gpu.md"
        content = "# GPU制度\n- 制度ID: GPU-001\n- 关键词: GPU\n\n旧正文"
        path.write_text(content, encoding="utf-8")
        store = PolicyStore(directory)
        with patch.object(store, "_read_policy_file", wraps=store._read_policy_file) as read:
            store.search_policy("GPU")
            store.get_policy_detail("GPU-001")
            self.assertEqual(read.call_count, 1)
            path.write_text(content + "新增的制度内容", encoding="utf-8")
            result = store.get_policy_detail("GPU-001")
            self.assertEqual(read.call_count, 2)
            self.assertIn("新增的制度内容", result["content"])

    def test_policy_symlink_cannot_escape_allowed_directory(self):
        directory = self.directory / "policies"
        directory.mkdir()
        outside = self.directory / "private.md"
        outside.write_text("private", encoding="utf-8")
        (directory / "escape.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            PolicyStore(directory).search_policy("private")


if __name__ == "__main__":
    unittest.main()

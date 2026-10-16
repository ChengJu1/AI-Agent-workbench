"""覆盖 SDK 通过结果消息报告失败、轮数耗尽及审批之后失败的情况。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import ResultMessage, StreamEvent

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_registry import AgentRegistry
from app.services.claude_runtime import ClaudeRuntimeService
from app.services.conversation_service import ConversationService
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.tool_store import ToolStore
from app.tools.timesheet_tools import TimesheetToolsService


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        database = Database(Path(self.temporary.name) / "test.db")
        database.initialize()
        self.store = ConversationStore(database)
        self.audit = ToolStore(database)
        self.registry = AgentRegistry()
        self.agent = self.registry.get_agent("timesheet_assistant")
        self.id = self.store.create(self.agent.id)
        self.tools = TimesheetToolsService(store=self.audit)
        self.runtime = ClaudeRuntimeService(tools_service=self.tools, audit_store=self.audit)
        self.service = ConversationService(self.registry, self.store, self.audit, self.runtime)

    def collect(self, query):
        async def run():
            prepared = self.service.prepare(self.id, "生成工时")
            return [event async for event in self.service.stream(self.id, "生成工时", prepared)]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch(
            "app.services.claude_runtime.query", query
        ), patch("app.services.claude_runtime.logger.exception"), patch(
            "app.services.conversation_service.logger.exception"
        ):
            return asyncio.run(run())

    def result(self, subtype="success", is_error=False):
        return ResultMessage(
            subtype=subtype, is_error=is_error, duration_ms=1, duration_api_ms=1,
            num_turns=1, session_id=self.id,
            result="private-provider-details", errors=["private-provider-details"],
        )

    def delta(self):
        return StreamEvent(
            uuid="event", session_id=self.id,
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "部分回复"}},
        )

    def test_failed_result_does_not_report_success_or_expose_internal_details(self):
        async def query(**kwargs):
            yield self.delta()
            yield self.result(is_error=True)

        events = self.collect(query)
        self.assertEqual([event["type"] for event in events], ["delta", "error"])
        self.assertNotIn("private-provider-details", json.dumps(events))
        self.assertEqual(self.store.get_messages(self.id)[-1]["content"], "部分回复")
        self.assertNotIn(self.id, self.service._active)

    def test_non_success_subtype_is_rejected_even_without_error_flag(self):
        async def query(**kwargs):
            yield self.result(subtype="error_max_turns")

        events = self.collect(query)
        self.assertEqual([event["type"] for event in events], ["error"])

    def test_pending_action_is_delivered_before_runtime_failure(self):
        async def query(**kwargs):
            # 模拟 SDK 工具成功创建审批后，后续模型调用抛出异常。
            response = self.tools._create_pending_action(
                self.id, self.agent, "timesheet_cli", "submit_timesheet",
                {"draft": {"records": [{"date": "2026-10-16", "task": "开发", "hours": 1}], "total_hours": 1}},
                session.pending_actions,
            )
            self.assertNotIn("is_error", response)
            yield self.delta()
            raise RuntimeError("private-provider-details")

        session = self.tools.create_session(self.id, self.agent)
        with patch.object(self.tools, "create_session", return_value=session):
            events = self.collect(query)
        self.assertEqual(
            [event["type"] for event in events], ["delta", "approval_required", "error"]
        )
        self.assertEqual(events[1]["action"]["id"], self.audit.get_pending_actions(self.id)[0]["id"])

    def test_successful_result_preserves_normal_stream_contract(self):
        async def query(**kwargs):
            yield self.delta()
            yield self.result()

        self.assertEqual([event["type"] for event in self.collect(query)], ["delta", "done"])

    def test_closing_reply_immediately_closes_sdk_query(self):
        closed = []

        async def query(**kwargs):
            try:
                yield self.delta()
            finally:
                closed.append(True)

        async def run():
            prepared = self.service.prepare(self.id, "请回复")
            stream = self.service.stream(self.id, "请回复", prepared)
            self.assertEqual((await anext(stream))["type"], "delta")
            await stream.aclose()
            self.assertEqual(closed, [True])
            self.assertNotIn(self.id, self.service._active)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch(
            "app.services.claude_runtime.query", query
        ):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

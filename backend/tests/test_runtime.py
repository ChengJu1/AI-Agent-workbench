"""覆盖 SDK 通过结果消息报告失败、轮数耗尽及审批之后失败的情况。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ProcessError, ResultMessage, StreamEvent, ToolUseBlock

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

    def missing_session(self, session_id=None):
        return ProcessError(
            f"Claude Code returned an error result: No conversation found with session ID: {session_id or self.id}",
            exit_code=1,
        )

    def test_missing_sdk_session_restores_history_without_deleting_chat(self):
        self.store.add_message(self.id, 'user', '之前的任务条件')
        self.store.add_message(self.id, 'assistant', '之前的解释，不是新的执行授权')
        calls = []

        async def query(prompt, options):
            calls.append((prompt, options))
            if len(calls) == 1:
                raise self.missing_session()
            yield self.delta()
            yield self.result()

        events = self.collect(query)
        self.assertEqual([e['type'] for e in events], ['delta', 'done'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1].resume, self.id)
        self.assertIsNone(calls[1][1].resume)
        self.assertEqual(calls[1][1].session_id, self.id)
        self.assertIn('之前的任务条件', calls[1][0])
        self.assertIn('不是新的操作授权', calls[1][0])
        self.assertTrue(calls[1][0].endswith('生成工时'))
        self.assertEqual(len(self.store.get_messages(self.id)), 4)
        self.assertEqual(calls[0][1].allowed_tools, calls[1][1].allowed_tools)
        self.assertEqual(calls[0][1].permission_mode, calls[1][1].permission_mode)

    def test_existing_sdk_session_resumes_without_replaying_history(self):
        self.store.add_message(self.id, 'assistant', '历史回复')
        calls = []

        async def query(prompt, options):
            calls.append((prompt, options))
            yield self.result()

        self.assertEqual(self.collect(query)[-1]['type'], 'done')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], '生成工时')
        self.assertEqual(calls[0][1].resume, self.id)

    def test_recovery_retries_once_and_reports_session_error_safely(self):
        self.agent = self.registry.get_agent('policy_qa_assistant')
        self.id = self.store.create(self.agent.id)
        self.store.add_message(self.id, 'assistant', '历史回复')
        calls = []

        async def query(**kwargs):
            calls.append(kwargs)
            raise self.missing_session()
            yield

        events = self.collect(query)
        self.assertEqual(len(calls), 2)
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('会话', events[-1]['content'])
        self.assertNotIn('MCP', events[-1]['content'])
        self.assertNotIn(self.id, events[-1]['content'])

    def test_no_recovery_after_any_sdk_output_or_tool_call(self):
        for message in [self.delta(), AssistantMessage(content=[ToolUseBlock(
            id='tool-before-error', name='mcp__example__write', input={},
        )], model='test-model')]:
            calls = []

            async def query(**kwargs):
                calls.append(kwargs)
                yield message
                raise self.missing_session()

            self.store.add_message(self.id, 'assistant', '历史回复')
            self.assertEqual(self.collect(query)[-1]['type'], 'error')
            self.assertEqual(len(calls), 1)

    def test_unrelated_process_error_or_other_session_is_not_retried(self):
        for error in [ProcessError('transport failed', exit_code=1), self.missing_session('other-id')]:
            calls = []

            async def query(**kwargs):
                calls.append(kwargs)
                raise error
                yield

            self.store.add_message(self.id, 'assistant', '历史回复')
            self.assertEqual(self.collect(query)[-1]['type'], 'error')
            self.assertEqual(len(calls), 1)

    def test_recovered_history_is_bounded_and_only_contains_current_conversation(self):
        other_id = self.store.create(self.agent.id)
        self.store.add_message(other_id, 'user', '其他会话的秘密')
        for i in range(30):
            self.store.add_message(self.id, 'assistant', f'历史{i}：' + '字' * 3000)
        calls = []

        async def query(prompt, options):
            calls.append(prompt)
            if len(calls) == 1:
                raise self.missing_session()
            yield self.result()

        self.assertEqual(self.collect(query)[-1]['type'], 'done')
        self.assertLess(len(calls[1]), 33000)
        self.assertNotIn('其他会话的秘密', calls[1])
        self.assertIn('历史29', calls[1])
        self.assertNotIn('历史0：', calls[1])


if __name__ == "__main__":
    unittest.main()

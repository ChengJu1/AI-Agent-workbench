"""Resume after decided actions: one platform notice built from records, never authorization or a replay."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.continuation import MAX_CONTINUATIONS


DRAFT = {'draft': {'records': [{'date': '2026-10-21', 'task': '合成任务', 'hours': 1}], 'total_hours': 1}}


class TurnModel(FakeListChatModel):
    """Stands in for the model: records the turn's input and lets the test create pending actions mid-turn."""
    on_call: object = Field(default=None, exclude=True)

    def bind_tools(self, tools, **kwargs):
        return self

    async def _astream(self, messages, **kwargs):
        self.on_call(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content='合成回答', chunk_position='last'))


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.agent = self.services.registry.get_agent('timesheet_assistant')
        self.cid = self.services.store.create(self.agent.id)
        self.prompts = []
        self.services.deep_agents.model_factory = lambda: TurnModel(responses=['unused'], on_call=self.model_called)
        self.executions = []
        execute = patch.object(self.services.approvals.cli_adapter, 'execute', side_effect=self.execute)
        execute.start()
        self.addCleanup(execute.stop)
        self.fail_execution = False
        self.create = 0

    def execute(self, *args, **kwargs):
        self.executions.append(args)
        if self.fail_execution:
            raise RuntimeError('合成执行失败')
        return {'submission_id': 'S-1'}

    def model_called(self, messages):
        self.prompts.append(messages[-1].content)  # The turn's input: the user's text or the platform notice.
        for _ in range(self.create):
            self.services.tool_store.create_pending_action(self.cid, self.agent.id, 'timesheet_cli', 'submit_timesheet', DRAFT)

    def turn(self, actions=1, text='请提交合成工时'):
        self.create = actions
        response = self.client.post(f'/api/conversations/{self.cid}/messages/stream', json={'content': text})
        self.assertEqual(response.status_code, 200)
        self.create = 0
        return [action['id'] for action in self.services.tool_store.get_pending_actions(self.cid)][-actions:] if actions else []

    def decide(self, action_id, approved=True):
        return self.client.post(f'/api/pending-actions/{action_id}/decision', json={'approved': approved})

    def resume(self, action_id):
        response = self.client.post(f'/api/conversations/{self.cid}/continue', json={'action_id': action_id})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        return response, events

    def test_approved_result_resumes_once_with_a_record_built_notice(self):
        [action] = self.turn()
        decided = self.decide(action).json()
        self.assertEqual((decided['status'], decided['continuation_available']), ('approved', True))
        response, events = self.resume(action)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([event['type'] for event in events][:2], ['platform_notice', 'delta'])
        self.assertEqual(events[-1]['type'], 'done')
        notice = events[0]['content']
        for text in (action, '已执行', 'S-1', '不是新的授权', '必须重新生成待确认操作'):
            self.assertIn(text, notice)
        self.assertEqual(self.prompts[-1], notice)  # The runtime gets exactly the server's notice.
        self.assertEqual(len(self.executions), 1)  # Resuming never executes the action again.
        stored = [m for m in self.services.store.get_messages(self.cid) if m['role'] == 'platform']
        self.assertEqual((stored[0]['content'], stored[0]['action_ids']), (notice, [action]))
        again, _ = self.resume(action)
        self.assertEqual(again.status_code, 409)
        self.assertIn('不会重复继续', again.json()['detail'])

    def test_cancelled_and_failed_results_resume_without_retrying(self):
        [cancelled] = self.turn()
        self.assertTrue(self.decide(cancelled, approved=False).json()['continuation_available'])
        _, events = self.resume(cancelled)
        self.assertIn('用户已取消', events[0]['content'])
        self.assertEqual(self.executions, [])
        [failed] = self.turn()
        self.fail_execution = True
        self.assertEqual(self.decide(failed).status_code, 502)
        self.assertTrue(self.services.conversations.continuation_available(self.services.tool_store.get_pending_action(failed)))
        _, events = self.resume(failed)
        self.assertIn('执行失败', events[0]['content'])
        self.assertIn('不要自行重试', events[0]['content'])
        self.assertEqual(len(self.executions), 1)

    def test_waits_until_every_action_of_the_turn_is_decided_then_reports_all(self):
        first, second = self.turn(actions=2)
        self.assertFalse(self.decide(first).json()['continuation_available'])
        response, _ = self.resume(first)
        self.assertEqual(response.status_code, 409)
        self.assertIn('未处理完', response.json()['detail'])
        self.assertTrue(self.decide(second, approved=False).json()['continuation_available'])
        _, events = self.resume(first)
        self.assertIn(first, events[0]['content'])
        self.assertIn(second, events[0]['content'])

    def test_newer_message_unknown_action_and_chain_limit_block_resuming(self):
        [action] = self.turn()
        with self.services.store.database.connection() as connection:
            connection.execute("UPDATE pending_actions SET created_at=datetime('now','-1 minute') WHERE id=?", (action,))
        self.turn(actions=0, text='先不管那个，换个话题')
        self.assertFalse(self.decide(action).json()['continuation_available'])
        response, _ = self.resume(action)
        self.assertIn('已有新消息', response.json()['detail'])
        other = self.services.store.create(self.agent.id)
        response = self.client.post(f'/api/conversations/{other}/continue', json={'action_id': action})
        self.assertEqual(response.status_code, 409)
        self.assertIn('没有这条操作', response.json()['detail'])
        [action] = self.turn()
        self.decide(action)
        for index in range(MAX_CONTINUATIONS):
            self.services.store.add_message(self.cid, 'platform', f'合成通知 {index}', action_ids=[f'synthetic-{index}'])
        response, _ = self.resume(action)
        self.assertIn('连续自动继续', response.json()['detail'])

    def test_notice_is_not_user_text_for_requirements(self):
        [action] = self.turn()
        self.decide(action)
        self.resume(action)
        state = self.services.conversations.task_context.build_task_context(self.cid, self.agent)
        self.assertNotIn('必须重新生成待确认操作', state)
        stored = self.services.store.get_messages(self.cid)
        self.assertEqual([m['role'] for m in stored].count('platform'), 1)


if __name__ == '__main__':
    unittest.main()

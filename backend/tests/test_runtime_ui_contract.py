"""Stage 5 settings, summary handoff and historical telemetry; synthetic data only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError


USAGE = {'runtime': 'claude_sdk', 'input_tokens': None, 'output_tokens': 7,
         'cache_read_input_tokens': None, 'cache_creation_input_tokens': None, 'model_calls': 1,
         'tool_calls': 1, 'first_token_ms': 1.0, 'duration_ms': 2.0, 'status': 'complete', 'context_estimate': {}}


class RuntimeUIContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / 'synthetic.db', deepagents_enabled=True)
        self.services = build_services(self.settings)
        self.agent = 'timesheet_assistant'
        self.client = TestClient(create_app(settings=self.settings, services=self.services))
        self.addCleanup(self.client.close)

    def test_default_and_override_are_persistent_without_changing_existing_runtime(self):
        original = self.client.post('/api/conversations', json={'agent_id': self.agent}).json()
        self.assertEqual(original['runtime'], 'claude_sdk')
        self.assertEqual(self.client.get('/api/runtime-options').json(), {'deep_agents_enabled': True})
        self.assertEqual(self.client.put(f'/api/agents/{self.agent}/runtime', json={'runtime': 'deep_agents'}).status_code, 200)
        created = self.client.post('/api/conversations', json={'agent_id': self.agent}).json()
        self.assertEqual(created['runtime'], 'deep_agents')
        override = self.client.post('/api/conversations', json={'agent_id': self.agent, 'runtime': 'claude_sdk'}).json()
        self.assertEqual(override['runtime'], 'claude_sdk')
        self.assertEqual(self.services.store.get_runtime(original['conversation_id']), 'claude_sdk')
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.store.default_runtime(self.agent), 'deep_agents')
        agent = next(agent for agent in self.client.get('/api/agents').json() if agent['id'] == self.agent)
        self.assertEqual(agent['default_runtime'], 'deep_agents')

    def test_disabled_flag_hides_options_and_falls_back_without_erasing_preference(self):
        self.services.registry.store.set_default_runtime(self.agent, 'deep_agents')
        disabled = build_services(Settings(database_path=self.settings.database_path))
        client = TestClient(create_app(services=disabled))
        self.addCleanup(client.close)
        self.assertEqual(client.get('/api/runtime-options').json(), {'deep_agents_enabled': False})
        self.assertEqual(client.post('/api/conversations', json={'agent_id': self.agent}).json()['runtime'], 'claude_sdk')
        self.assertEqual(client.post('/api/conversations', json={'agent_id': self.agent, 'runtime': 'deep_agents'}).status_code, 409)
        self.assertEqual(client.put(f'/api/agents/{self.agent}/runtime', json={'runtime': 'deep_agents'}).status_code, 409)
        self.assertEqual(disabled.registry.store.default_runtime(self.agent), 'deep_agents')
        self.assertEqual(client.put('/api/agents/missing/runtime', json={'runtime': 'claude_sdk'}).status_code, 404)
        self.assertEqual(client.put(f'/api/agents/{self.agent}/runtime', json={'runtime': 'invalid'}).status_code, 422)

    def test_handoff_copies_reviewed_text_without_model_or_approval_execution(self):
        source = self.services.conversations.create(self.agent, 'claude_sdk')
        self.services.store.add_message(source, 'user', '合成任务。硬性要求：不得提交。')
        self.services.store.add_message(source, 'assistant', '已准备草稿，待确认。')
        action = self.services.tool_store.create_pending_action(source, self.agent, 'timesheet_cli', 'submit_timesheet', {})
        original = self.services.store.get_messages(source)
        generated = self.client.get(f'/api/conversations/{source}/work-summary').json()
        self.assertEqual(generated['source_runtime'], 'claude_sdk')
        self.assertIn('不得提交', generated['summary'])
        self.assertIn(action, generated['summary'])
        edited = generated['summary'] + '\n用户补充：只考虑上海。'
        with patch('app.services.claude_runtime.query', side_effect=AssertionError('No model calls')), \
             patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('No model calls')), \
             patch.object(self.services.approvals, 'decide', side_effect=AssertionError('No approval execution')):
            response = self.client.post(f'/api/conversations/{source}/copy-summary', json={'runtime': 'deep_agents', 'summary': edited})
        self.assertEqual(response.status_code, 200, response.text)
        target = response.json()['conversation_id']
        self.assertEqual(self.services.store.get_runtime(target), 'deep_agents')
        self.assertIn(edited, self.services.store.get_messages(target)[0]['content'])
        self.assertIn('不是新操作授权', self.services.store.get_messages(target)[0]['content'])
        self.assertEqual(self.services.store.get_messages(source), original)
        self.assertEqual(self.services.tool_store.get_pending_actions(target), [])
        self.assertEqual(self.services.tool_store.get_pending_action(action)['status'], 'pending')
        self.assertEqual(self.services.store.get_runtime(source), 'claude_sdk')

    def test_handoff_rejects_active_source_same_runtime_and_invalid_text(self):
        source = self.services.conversations.create(self.agent)
        path = f'/api/conversations/{source}'
        self.assertEqual(self.client.post(path + '/copy-summary', json={'runtime': 'claude_sdk', 'summary': '合成'}).status_code, 409)
        self.assertEqual(self.client.post(path + '/copy-summary', json={'runtime': 'deep_agents', 'summary': ' '}).status_code, 422)
        prepared = self.services.conversations.prepare(source, '合成')
        try:
            self.assertEqual(self.client.get(path + '/work-summary').status_code, 409)
            self.assertEqual(self.client.post(path + '/copy-summary', json={'runtime': 'deep_agents', 'summary': '合成'}).status_code, 409)
        finally:
            self.services.conversations.release(source, prepared)

    def test_usage_and_argument_free_tool_status_restore_after_restart_and_failure(self):
        base = self.services.knowledge.store.create_base('合成资料', '')
        self.services.registry.bind_knowledge(self.agent, [base['id']])
        for failed in (False, True):
            source = self.services.conversations.create(self.agent)
            class SyntheticRuntime:
                async def stream(self, *args):
                    yield {'type': 'tool_started', 'tool_name': 'synthetic', 'call_id': 'one', 'private_args': 'DO_NOT_PERSIST'}
                    yield {'type': 'tool_finished', 'tool_name': 'synthetic', 'call_id': 'one', 'success': False}
                    yield {'type': 'usage', 'usage': {**USAGE, 'status': 'failed' if failed else 'complete'}}
                    if failed:
                        raise ServiceError('合成错误', 502)
                    yield {'type': 'delta', 'content': '合成回答'}
                def delete_conversation(self, *args):
                    pass
            self.services.conversations.runtime = SyntheticRuntime()
            self.client.post(f'/api/conversations/{source}/messages/stream', json={'content': '合成请求'})
            fresh = build_services(self.settings)
            history = fresh.store.get_messages(source)
            assistant = history[-1]
            self.assertEqual(assistant['usage']['output_tokens'], 7)
            self.assertIsNone(assistant['usage']['input_tokens'])
            self.assertEqual(assistant['status'], 'failed' if failed else 'complete')
            self.assertEqual(len(assistant['tool_activity']), 2)
            self.assertNotIn('DO_NOT_PERSIST', str(assistant))
            restored = self.client.get(f'/api/conversations/{source}/messages').json()[-1]
            self.assertEqual(restored, assistant)

    def test_old_history_has_no_fabricated_usage(self):
        cid = self.services.conversations.create(self.agent)
        self.services.store.add_message(cid, 'assistant', '原有回答')
        self.assertEqual(self.client.get(f'/api/conversations/{cid}/messages').json(), [{'role': 'assistant', 'content': '原有回答'}])

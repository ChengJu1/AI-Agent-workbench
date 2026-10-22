"""Single-runtime conversation contract, read-only archives and historical telemetry; synthetic data only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError


USAGE = {'runtime': 'deep_agents', 'input_tokens': None, 'output_tokens': 7,
         'cache_read_input_tokens': None, 'cache_creation_input_tokens': None, 'model_calls': 1,
         'tool_calls': 1, 'first_token_ms': 1.0, 'duration_ms': 2.0, 'status': 'complete', 'context_estimate': {}}


class RuntimeUIContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / 'synthetic.db')
        self.services = build_services(self.settings)
        self.agent = 'timesheet_assistant'
        self.client = TestClient(create_app(settings=self.settings, services=self.services))
        self.addCleanup(self.client.close)

    def test_new_conversations_need_no_runtime_choice_and_removed_endpoints_are_gone(self):
        created = self.client.post('/api/conversations', json={'agent_id': self.agent})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(set(created.json()), {'conversation_id'})
        self.assertEqual(self.services.store.get_runtime(created.json()['conversation_id']), 'deep_agents')
        self.assertEqual(self.client.post('/api/conversations', json={'agent_id': self.agent, 'runtime': 'claude_sdk'}).status_code, 422)
        cid = created.json()['conversation_id']
        for method, path in [('get', '/api/runtime-options'), ('put', f'/api/agents/{self.agent}/runtime'),
                             ('get', f'/api/conversations/{cid}/work-summary'), ('post', f'/api/conversations/{cid}/copy-summary')]:
            self.assertIn(getattr(self.client, method)(path).status_code, (404, 405), path)
        self.assertNotIn('default_runtime', self.client.get('/api/agents').json()[0])

    def test_claude_sdk_conversations_are_read_only_archives(self):
        archived = self.services.store.create(self.agent, 'claude_sdk')
        self.services.store.add_message(archived, 'user', '合成历史请求')
        self.services.store.add_message(archived, 'assistant', '合成历史回答')
        action = self.services.tool_store.create_pending_action(archived, self.agent, 'timesheet_cli', 'submit_timesheet', {})
        current = self.services.conversations.create(self.agent)
        listing = {item['id']: item['archived'] for item in self.client.get(f'/api/agents/{self.agent}/conversations').json()}
        self.assertEqual(listing, {archived: True, current: False})
        original = self.client.get(f'/api/conversations/{archived}/messages').json()
        self.assertEqual([m['content'] for m in original], ['合成历史请求', '合成历史回答'])
        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('No model calls')):
            sent = self.client.post(f'/api/conversations/{archived}/messages/stream', json={'content': '继续'})
            resumed = self.client.post(f'/api/conversations/{archived}/continue', json={'action_id': action})
        for response in (sent, resumed):
            self.assertEqual(response.status_code, 409)
            self.assertIn('只能查看', response.json()['detail'])
        self.assertEqual(self.client.get(f'/api/conversations/{archived}/messages').json(), original)
        self.assertNotIn(archived, self.services.conversations._active)
        self.assertEqual(self.client.delete(f'/api/conversations/{archived}').status_code, 200)
        self.assertFalse(self.services.store.exists(archived))

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

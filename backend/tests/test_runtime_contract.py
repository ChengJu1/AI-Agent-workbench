"""Golden stage-0 event ordering with the new runtime protocol and real tool handlers."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_agent_sdk import ResultMessage, StreamEvent
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.runtime import AgentRuntime, RuntimeContext
from app.runtime.task_context import TaskContextBuilder
from app.models.applications import ApplicationSave
from app.models.profiles import ProfileSave


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))
        self.runtime = self.services.conversations.runtime
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.agent = self.services.registry.get_agent('timesheet_assistant')
        self.cid = self.services.store.create(self.agent.id)

    def delta(self, text='回答'):
        return StreamEvent(uuid='delta', session_id=self.cid,
                           event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': text}})

    def result(self, failed=False):
        return ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1, num_turns=1,
                             session_id=self.cid, is_error=failed, usage={'input_tokens': 20, 'output_tokens': 2})

    def collect(self, query):
        async def run():
            prepared = self.services.conversations.prepare(self.cid, '合成任务')
            return [event async for event in self.services.conversations.stream(self.cid, '合成任务', prepared)]
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fake', 'ANTHROPIC_MODEL': 'deepseek-v4-pro'}), patch('app.services.claude_runtime.query', query):
            return [event for event in asyncio.run(run()) if event['type'] not in ('tool_started', 'tool_finished')]

    def test_normal_reply_preserves_stage0_event_contract(self):
        async def query(**kwargs):
            yield self.delta()
            yield self.result()
        events = self.collect(query)
        self.assertEqual([event['type'] for event in events], ['delta', 'usage', 'done'])
        self.assertEqual(events[0], {'type': 'delta', 'content': '回答'})
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['content'], '回答')
        self.assertIsInstance(self.runtime, AgentRuntime)

    def test_pending_approval_preserves_event_order_and_never_executes(self):
        async def query(prompt, options):
            async with create_connected_server_and_client_session(options.mcp_servers['timesheet_cli']['instance']) as client:
                result = await client.call_tool('submit_timesheet', {'draft': {'records': [{'date': '2026-10-21', 'task': '合成任务', 'hours': 1}], 'total_hours': 1}})
                self.assertFalse(result.isError)
            yield self.delta('等待确认')
            yield self.result()
        with patch.object(self.runtime._tools_service._adapter, 'execute', side_effect=AssertionError('Must not execute')):
            events = self.collect(query)
        self.assertEqual([event['type'] for event in events], ['delta', 'approval_required', 'usage', 'done'])
        self.assertEqual(events[1]['action']['status'], 'pending')
        self.assertEqual(events[1]['action']['id'], self.services.tool_store.get_pending_actions(self.cid)[0]['id'])

    def test_error_preserves_partial_reply_and_safe_event_contract(self):
        async def query(**kwargs):
            yield self.delta()
            yield self.result(failed=True)
        events = self.collect(query)
        self.assertEqual([event['type'] for event in events], ['delta', 'usage', 'error'])
        self.assertEqual(events[-1], {'type': 'error', 'content': '模型未能完成本轮回复，请稍后重试。'})
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['content'], '回答')

    def test_knowledge_tool_records_evidence_without_sdk_tool_messages(self):
        base = self.services.knowledge.store.create_base('合成资料', '')
        self.services.knowledge.ingest(base['id'], 'synthetic.md', 'GPU 申请需要审批。'.encode())
        created = self.client.post('/api/agents', json={'name': '引用测试', 'description': '合成', 'system_prompt': '查资料',
                                                      'knowledge_base_ids': [base['id']]}).json()
        self.cid = self.services.store.create(created['id'])
        async def query(prompt, options):
            async with create_connected_server_and_client_session(options.mcp_servers['workbench_knowledge']['instance']) as client:
                result = await client.call_tool('search_knowledge', {'knowledge_base_id': base['id'], 'query': 'GPU'})
                citation = json.loads(result.content[0].text)['matches'][0]['citation_link']
            yield self.delta(f'需要审批。[1]({citation})')
            yield self.result()
        events = self.collect(query)
        self.assertEqual([event['type'] for event in events], ['knowledge', 'delta', 'knowledge', 'usage', 'done'])
        self.assertEqual(events[0]['evidence'], events[2]['evidence'])
        self.assertEqual(events[0]['evidence']['status'], 'matched')
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['knowledge'], events[0]['evidence'])

    def test_service_only_needs_runtime_protocol(self):
        observed = []
        class PlainRuntime:
            async def stream(self, conversation_id, agent, user_message, context):
                observed.append(context)
                yield {'type': 'delta', 'content': '独立运行时'}
            def delete_conversation(self, conversation_id):
                pass
        self.services.conversations.runtime = PlainRuntime()
        async def run():
            prepared = self.services.conversations.prepare(self.cid, '合成任务')
            return [event async for event in self.services.conversations.stream(self.cid, '合成任务', prepared)]
        events = asyncio.run(run())
        self.assertEqual(events, [{'type': 'delta', 'content': '独立运行时'}, {'type': 'done'}])
        self.assertIsInstance(observed[0], RuntimeContext)
        self.assertIn('本轮结构化任务状态', observed[0].business_context)

    def test_delete_only_targets_sdk_session_in_backend_project(self):
        with patch('app.services.claude_runtime.delete_session') as delete:
            self.runtime.delete_conversation(self.cid)
            delete.assert_called_once_with(self.cid, directory=str(Path(__file__).resolve().parents[1]))
        with patch('app.services.claude_runtime.delete_session', side_effect=FileNotFoundError):
            self.runtime.delete_conversation(self.cid)

    def test_task_context_refreshes_database_versions_and_scopes_capabilities(self):
        application = self.services.applications.save(ApplicationSave(company='合成公司', position='岗位'))
        profile = self.services.profiles.save(ProfileSave(name='合成档案', data={}))
        agent = self.agent.model_copy(update={'platform_capabilities': ['applications']})
        builder = TaskContextBuilder(self.services.store.database, self.services.tool_store)
        first = builder.build_task_context(self.cid, agent)
        self.assertIn(application['id'], first)
        self.assertIn(profile['id'], first)
        self.assertIn('"latest_version": 1', first)
        self.services.profiles.save(ProfileSave(name='合成档案', data={}, expected_version=1), profile['id'])
        action_id = self.services.tool_store.create_pending_action(self.cid, agent.id, 'timesheet_cli', 'submit_timesheet', {})
        other = self.services.store.create(agent.id)
        other_action = self.services.tool_store.create_pending_action(other, agent.id, 'timesheet_cli', 'submit_timesheet', {})
        second = builder.build_task_context(self.cid, agent)
        self.assertIn('"latest_version": 2', second)
        self.assertIn(action_id, second)
        self.assertNotIn(other_action, second)
        restricted = builder.build_task_context(self.cid, self.agent)
        self.assertNotIn(application['id'], restricted)
        self.assertNotIn(profile['id'], restricted)
        self.assertIn('"hard_requirements_status": "not_stored"', restricted)

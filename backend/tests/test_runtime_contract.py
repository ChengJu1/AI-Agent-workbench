"""Reply event ordering through the runtime protocol and real tool handlers."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.runtime import AgentRuntime, RuntimeContext
from app.runtime.task_context import TaskContextBuilder
from app.kits.job_search.models import ApplicationSave
from app.kits.job_search.profiles import ProfileSave
from test_deep_agents import FakeDeepModel, ToolModel


DRAFT = {'draft': {'records': [{'date': '2026-10-21', 'task': '合成任务', 'hours': 1}], 'total_hours': 1}}


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

    def collect(self, model):
        """Event types of one turn, consecutive repeats folded (the fake model streams text in pieces)."""
        self.services.deep_agents.model_factory = lambda: model
        async def run():
            prepared = self.services.conversations.prepare(self.cid, '合成任务')
            return [event async for event in self.services.conversations.stream(self.cid, '合成任务', prepared)]
        events = [event for event in asyncio.run(run()) if event['type'] not in ('tool_started', 'tool_finished')]
        folded = [event['type'] for index, event in enumerate(events) if index == 0 or events[index - 1]['type'] != event['type']]
        return events, folded

    def test_normal_reply_event_contract(self):
        events, folded = self.collect(FakeDeepModel(responses=['回答']))
        self.assertEqual(folded, ['delta', 'usage', 'done'])
        self.assertEqual(''.join(e['content'] for e in events if e['type'] == 'delta'), '回答')
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['content'], '回答')
        self.assertIsInstance(self.runtime, AgentRuntime)

    def test_pending_approval_is_announced_before_done_and_never_executes(self):
        model = ToolModel(responses=['unused'], action='mcp__timesheet_cli__submit_timesheet', arguments=DRAFT)
        with patch.object(self.services.deep_agents.tool_services.timesheets._adapter, 'execute', side_effect=AssertionError('Must not execute')):
            events, folded = self.collect(model)
        self.assertEqual(folded, ['delta', 'approval_required', 'usage', 'done'])
        action = next(e['action'] for e in events if e['type'] == 'approval_required')
        self.assertEqual(action['status'], 'pending')
        self.assertEqual(action['id'], self.services.tool_store.get_pending_actions(self.cid)[0]['id'])

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

    def test_task_context_refreshes_database_versions_and_scopes_capabilities(self):
        application = self.services.kits['applications'].applications.save(ApplicationSave(company='合成公司', position='岗位'))
        profile = self.services.kits['applications'].profiles.save(ProfileSave(name='合成档案', data={}))
        agent = self.agent.model_copy(update={'platform_capabilities': ['applications']})
        builder = TaskContextBuilder(self.services.store.database, self.services.tool_store)
        first = builder.build_task_context(self.cid, agent)
        self.assertIn(application['id'], first)
        self.assertIn(profile['id'], first)
        self.assertIn('"latest_version": 1', first)
        self.services.kits['applications'].profiles.save(ProfileSave(name='合成档案', data={}, expected_version=1), profile['id'])
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

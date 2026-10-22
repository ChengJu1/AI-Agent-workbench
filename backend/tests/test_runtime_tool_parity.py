"""Exercise real shared handlers through the Deep Agents loop, without real models."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from app.application import create_app
from app.config import Settings
from app.container import build_services
from mcp_servers.notes_server import create_notes_server
from test_deep_agents import ToolModel
from test_platform_capabilities import FakeBrowser


class ParityModel(ToolModel):
    fail_after_tool: bool = False

    async def _astream(self, messages, **kwargs):
        start = max(i for i, message in enumerate(messages) if message.type == 'human')
        current = messages[start:]
        if self.fail_after_tool and any(message.type == 'tool' for message in current):
            raise RuntimeError('synthetic model failure')
        async for chunk in super()._astream(current, **kwargs):
            # One text chunk in either runtime makes event sequences comparable.
            yield chunk


class RuntimeToolParityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.agent = self.services.registry.get_agent('timesheet_assistant')

    def run_pair(self, server, action, arguments, failed=False, cids=None):
        """One Deep Agents turn that calls the tool; a one-item list so callers can loop over results."""
        cid = cids or self.services.conversations.create(self.agent.id)
        model = ParityModel(responses=['unused'], action=f'mcp__{server}__{action}', arguments=arguments, fail_after_tool=failed)
        self.services.deep_agents.model_factory = lambda: model

        async def collect():
            prepared = self.services.conversations.prepare(cid, '合成任务')
            return [event async for event in self.services.conversations.stream(cid, '合成任务', prepared)]

        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real model forbidden')):
            events = asyncio.run(collect())
        statuses = [e for e in events if e['type'].startswith('tool_')]
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[0]['tool_name'], f'mcp__{server}__{action}')
        self.assertNotIn('arguments', str(statuses))
        return [(cid, events, model)]

    def test_submit_creates_pending_without_execution_even_after_model_failure(self):
        arguments = {'draft': {'records': [{'date': '2026-10-21', 'task': '合成任务', 'hours': 1}], 'total_hours': 1}}
        for failed in (False, True):
            with self.subTest(failed=failed), patch.object(self.services.deep_agents.tool_services.timesheets._adapter,
                    'execute', side_effect=AssertionError('Approval required')):
                results = self.run_pair('timesheet_cli', 'submit_timesheet', arguments, failed)
                for cid, events, model in results:
                    pending = self.services.tool_store.get_pending_actions(cid)
                    self.assertEqual(len(pending), 1)
                    self.assertEqual(pending[0]['status'], 'pending')
                    self.assertEqual(next(e['action']['id'] for e in events if e['type'] == 'approval_required'), pending[0]['id'])
                    self.assertEqual(events[-1]['type'], 'error' if failed else 'done')
                    self.assertTrue(next(e['success'] for e in events if e['type'] == 'tool_finished'))
                    self.assertEqual(self.services.tool_store.get_audit_logs(cid)[0]['status'], 'pending')

    def test_failed_business_tool_is_error_to_model_and_identical_status_to_ui(self):
        created = self.client.post('/api/agents', json={'name': '合成文件助手', 'description': '合成',
            'system_prompt': '核对文件', 'platform_capabilities': ['files']}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        results = self.run_pair('workbench_platform', 'read_file', {'file_id': 'file_' + '0' * 32})
        for cid, events, _ in results:
            self.assertFalse(next(e['success'] for e in events if e['type'] == 'tool_finished'))
            self.assertEqual(self.services.tool_store.get_audit_logs(cid)[0]['status'], 'failed')
        tool_message = next(m for m in results[0][2].seen[-1] if m.type == 'tool')
        self.assertEqual(tool_message.status, 'error')
        self.assertEqual(tool_message.content[0]['type'], 'text')

    def test_knowledge_evidence_survives_later_model_failure(self):
        base = self.services.knowledge.store.create_base('合成资料', '')
        self.services.knowledge.ingest(base['id'], 'synthetic.md', 'GPU 申请需要审批。'.encode())
        created = self.client.post('/api/agents', json={'name': '合成资料助手', 'description': '合成',
            'system_prompt': '核对资料', 'knowledge_base_ids': [base['id']]}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        for failed in (False, True):
            results = self.run_pair('workbench_knowledge', 'search_knowledge',
                                    {'knowledge_base_id': base['id'], 'query': 'GPU'}, failed)
            for cid, events, _ in results:
                evidence = [e['evidence'] for e in events if e['type'] == 'knowledge']
                self.assertTrue(evidence)
                self.assertEqual(evidence[0]['status'], 'matched')
                self.assertEqual(evidence[0], evidence[-1])
                self.assertEqual(self.services.store.get_messages(cid)[-1]['knowledge'], evidence[-1])

    def test_skill_loads_use_shared_version_and_reset_each_turn(self):
        skill = self.client.post('/api/skills', json={'name': '合成规则', 'description': '合成', 'content': '必须核对来源。'}).json()
        self.services.deep_agents.skill_read_budget_chars = len(skill['content'])
        self.services.conversations.skill_read_budget_chars = len(skill['content'])
        created = self.client.post('/api/agents', json={'name': '合成技能助手', 'description': '合成',
            'system_prompt': '按需读取', 'skill_ids': [skill['id']], 'skill_versions': {skill['id']: 1}}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        response = self.client.put(f"/api/skills/{skill['id']}", json={'name': '合成规则', 'description': '合成',
            'content': '第二版规则。', 'expected_version': 1})
        self.assertEqual(response.status_code, 200)
        cids = None
        for _ in range(2):
            results = self.run_pair('workbench_skills', 'load_skill', {'skill_id': skill['id']}, cids=cids)
            cids = results[0][0]
            snapshot = next(e['skills'] for e in results[0][1] if e['type'] == 'skills' and e['skills'])
            self.assertEqual(snapshot[0]['version'], 1)
            self.assertEqual(len(snapshot), 1)  # Loads reset each turn instead of accumulating.

    def test_external_notes_use_official_adapter_shared_audit_and_whitelist(self):
        base = self.services.knowledge.store.create_base('笔记 · 合成', '')
        self.services.knowledge.ingest(base['id'], 'synthetic.md', 'GPU 申请需要审批。'.encode())
        created = self.client.post('/api/agents', json={'name': '合成笔记助手', 'description': '合成',
            'system_prompt': '按需读取', 'tools': [{'type': 'mcp', 'name': 'my_notes', 'transport': 'http',
            'url': 'http://synthetic.invalid/mcp', 'actions': ['search_notes']}]}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        server = create_notes_server(self.services.store.database.path)

        @asynccontextmanager
        async def open_session(config):
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                yield session

        with patch('app.tools.external_tools.open_mcp_session', open_session):
            for failed in (False, True):
                results = self.run_pair('my_notes', 'search_notes', {'query': 'GPU'}, failed)
                for cid, events, _ in results:
                    evidence = [e['evidence'] for e in events if e['type'] == 'knowledge'][-1]
                    self.assertEqual(evidence['status'], 'matched')
                    self.assertEqual(evidence['notes_calls'], 1)
                    self.assertEqual(evidence['citations'][0]['source_kind'], 'notes_mcp')
                    self.assertEqual(self.services.tool_store.get_audit_logs(cid)[0]['status'], 'success')
                names = results[0][2].tool_names
                self.assertIn('mcp__my_notes__search_notes', names)
                self.assertNotIn('mcp__my_notes__read_note', names)
                self.assertNotIn('mcp__my_notes__list_notes', names)

    def test_browser_changes_remain_pending_with_same_shared_approval(self):
        fake = FakeBrowser()
        self.services.platform.browser = fake
        created = self.client.post('/api/agents', json={'name': '合成浏览器助手', 'description': '合成',
            'system_prompt': '等待确认', 'platform_capabilities': ['browser']}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        for failed in (False, True):
            results = self.run_pair('workbench_platform', 'browser_prepare_actions', {
                'session_id': 'browser_' + '1' * 32, 'snapshot_id': 'synthetic',
                'operations': [{'kind': 'click', 'element_id': 'e_1'}]}, failed)
            for cid, events, _ in results:
                pending = self.services.tool_store.get_pending_actions(cid)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]['status'], 'pending')
                self.assertEqual(next(e['action']['id'] for e in events if e['type'] == 'approval_required'), pending[0]['id'])
            self.assertEqual(fake.executed, 0)

    def test_application_profile_and_kit_share_existing_local_records(self):
        created = self.client.post('/api/agents', json={'name': '合成台账助手', 'description': '合成',
            'system_prompt': '核对台账', 'platform_capabilities': ['applications']}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        profile = self.client.post('/api/profiles', json={'name': '合成档案', 'data': {'basics': {'name': '合成人'}}}).json()
        application = self.client.post('/api/applications', json={'company': '合成公司', 'position': '合成岗位'}).json()
        for action, arguments in [
            ('application_read', {'application_id': application['id']}),
            ('application_profiles', {}),
            ('application_prepare_kit', {'application_id': application['id'], 'profile_id': profile['id'],
             'profile_version': 1, 'items': [{'label': '姓名', 'source': {'kind': 'profile', 'version': 1, 'ref': 'basics.name'}}]}),
        ]:
            results = self.run_pair('workbench_platform', action, arguments)
            for cid, events, _ in results:
                self.assertTrue(next(e['success'] for e in events if e['type'] == 'tool_finished'))
        saved = self.client.get(f"/api/applications/{application['id']}").json()
        self.assertEqual(saved['stage'], 'preparing')
        self.assertEqual(saved['kit']['items'][0]['value'], '合成人')
        self.assertFalse(saved['applied_at'])

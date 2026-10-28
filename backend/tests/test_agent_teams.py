"""Team membership, delegated child conversations and delete cascades; synthetic data only."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services


class AgentTeamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / 'synthetic.db')
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(settings=self.settings, services=self.services))
        self.addCleanup(self.client.close)

    def create_agent(self, name='合成助理'):
        response = self.client.post('/api/agents', json={'name': name, 'description': '测试用', 'system_prompt': '回答问题。',
                                                         'platform_capabilities': ['files']})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def create_conversation(self, agent_id):
        response = self.client.post('/api/conversations', json={'agent_id': agent_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['conversation_id']

    def delegate(self, parent, member):
        """Stand-in for the delegate tool until it exists: create the member's child conversation."""
        child = self.services.conversations.create(member)
        self.services.teams.store.add_delegation(parent, member, child)
        return child

    def propose(self, lead, cid, plan):
        """Stand-in for the propose_team tool: a team plan waiting in the confirmation list."""
        return self.services.tool_store.create_pending_action(cid, lead, 'workbench_team', 'team_plan', plan)

    def decide(self, action_id, approved=True, plan=None):
        return self.client.post(f'/api/pending-actions/{action_id}/decision', json={'approved': approved, **({'plan': plan} if plan else {})})

    def test_plan_is_validated_and_approval_creates_temporary_agents_within_the_leads_capabilities(self):
        lead, helper = self.create_agent('负责人'), self.create_agent('研究员')
        cid = self.create_conversation(lead)
        lead_agent = self.services.registry.get_agent(lead)
        validate = lambda plan: self.services.teams.validate_plan(lead_agent, plan)
        temp = {'name': '安全评审', 'instructions': '只看安全问题。', 'capabilities': ['files'], 'role': '挑安全问题'}
        self.assertEqual(validate({'summary': '评审', 'participants': [{'agent_id': helper}, temp]})['participants'][0]['name'], '研究员')
        for bad in ({'summary': '', 'participants': [temp]}, {'summary': '评审', 'participants': []},
                    {'summary': '评审', 'participants': [{**temp, 'capabilities': ['web']}]},
                    {'summary': '评审', 'participants': [{'agent_id': lead}]},
                    {'summary': '评审', 'participants': [{'agent_id': helper}, {'agent_id': helper}]},
                    {'summary': '评审', 'participants': [temp] * 6},
                    {'summary': '评审', 'participants': [{**temp, 'name': 'security_reviewer'}]}):
            with self.assertRaises(Exception):
                validate(bad)

        self.assertEqual(self.services.teams.approved_participants(cid), [])
        action = self.propose(lead, cid, validate({'summary': '评审', 'participants': [temp]}))
        self.assertIsNone(self.services.teams.approved_participants(cid))
        # 用户修改：把临时 Agent 换成自己的 Agent，再加一个去掉能力的临时 Agent。
        edited = {'summary': '评审', 'participants': [{'agent_id': helper, 'role': '查资料'}, {**temp, 'capabilities': []}]}
        self.assertEqual(self.decide(action, plan={'summary': '评审', 'participants': [{**temp, 'capabilities': ['web']}]}).status_code, 422)
        self.assertEqual(self.services.tool_store.get_pending_action(action)['status'], 'pending')
        response = self.decide(action, plan=edited)
        self.assertEqual(response.status_code, 200, response.text)
        result = self.services.tool_store.get_pending_action(action)['result']
        self.assertTrue(result['changed'])
        participants = self.services.teams.approved_participants(cid)
        self.assertEqual(participants[0], helper)
        temporary = self.services.registry.get_agent(participants[1])
        self.assertEqual((temporary.name, temporary.system_prompt, temporary.platform_capabilities), ('安全评审', '只看安全问题。', []))
        self.assertNotIn(participants[1], {agent['id'] for agent in self.client.get('/api/agents').json()})
        self.assertIn('用户修改过', response.json()['message'])
        self.assertEqual(self.decide(action).status_code, 409)

        rejected = self.propose(lead, cid, validate({'summary': '再来', 'participants': [temp]}))
        self.assertEqual(self.decide(rejected, approved=False).json()['status'], 'cancelled')
        self.assertEqual(self.services.teams.approved_participants(cid), participants)
        other = self.services.tool_store.create_pending_action(cid, lead, 'timesheet_cli', 'submit_timesheet', {})
        self.assertEqual(self.decide(other, plan=edited).status_code, 422)

    def test_child_conversations_are_listed_under_the_parent_only(self):
        lead, member = self.create_agent('负责人'), self.create_agent('成员')
        parent = self.create_conversation(lead)
        own = self.create_conversation(member)
        child = self.delegate(parent, member)
        self.services.store.add_message(child, 'user', '委派的任务')

        self.assertEqual([item['id'] for item in self.client.get(f'/api/agents/{member}/conversations').json()], [own])
        delegations = self.client.get(f'/api/conversations/{parent}/delegations').json()
        self.assertEqual([(item['member_agent_id'], item['member_name'], item['child_conversation_id']) for item in delegations],
                         [(member, '成员', child)])
        self.assertEqual(self.client.get(f'/api/conversations/{child}').json()['parent'],
                         {'parent_conversation_id': parent, 'lead_agent_id': lead, 'lead_agent_name': '负责人'})
        self.assertIsNone(self.client.get(f'/api/conversations/{parent}').json()['parent'])
        self.assertEqual(self.client.get('/api/conversations/missing').status_code, 404)
        self.assertEqual(self.client.get('/api/conversations/missing/delegations').status_code, 404)

        self.client.put(f'/api/conversations/{child}/archived', json={'archived': True})
        self.assertEqual(self.client.get('/api/conversations/archived').json(), [])
        response = self.client.post(f'/api/conversations/{child}/messages/stream', json={'content': '直接发消息'})
        self.assertEqual(response.status_code, 409)

    def test_deleting_the_parent_conversation_deletes_its_child_conversations(self):
        lead, member = self.create_agent('负责人'), self.create_agent('成员')
        parent = self.create_conversation(lead)
        child = self.delegate(parent, member)
        self.services.conversations._active[child] = object()
        self.assertEqual(self.client.delete(f'/api/conversations/{parent}').status_code, 409)
        self.assertTrue(self.services.store.exists(parent))
        self.assertNotIn(parent, self.services.conversations._active)
        self.services.conversations._active.pop(child)

        self.assertEqual(self.client.delete(f'/api/conversations/{parent}').status_code, 200)
        self.assertFalse(self.services.store.exists(child))
        with self.services.store.database.connection() as connection:
            self.assertIsNone(connection.execute('SELECT 1 FROM conversation_delegations').fetchone())

    def test_deleting_the_parent_or_a_member_removes_child_conversations_and_temporary_agents(self):
        lead, member = self.create_agent('负责人'), self.create_agent('成员')
        parent = self.create_conversation(lead)
        member_child = self.delegate(parent, member)
        temporary = self.services.teams.store.create_temporary(parent, lead, '临时', '说明', [])
        temporary_child = self.delegate(parent, temporary)
        self.assertEqual(self.client.get(f'/api/conversations/{temporary_child}').json()['agent_name'], '临时')
        self.assertTrue(self.client.get(f'/api/conversations/{parent}/delegations').json()[1]['temporary'])

        self.assertEqual(self.client.delete(f'/api/agents/{member}').json(), {'deleted': True, 'conversations': 1})
        self.assertFalse(self.services.store.exists(member_child))
        self.assertEqual(self.client.delete(f'/api/agents/{lead}').json(), {'deleted': True, 'conversations': 2})
        self.assertFalse(self.services.store.exists(temporary_child))
        self.assertIsNone(self.services.registry.get_agent(temporary))


if __name__ == '__main__':
    unittest.main()

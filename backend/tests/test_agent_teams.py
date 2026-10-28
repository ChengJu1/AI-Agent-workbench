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

    def team(self, lead):
        return [item['id'] for item in self.client.get(f'/api/agents/{lead}/team').json()['members']]

    def test_team_members_are_saved_in_order_and_validated(self):
        lead, first, second = self.create_agent('负责人'), self.create_agent('成员一'), self.create_agent('成员二')
        self.assertEqual(self.team(lead), [])
        response = self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [second, first, second]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item['id'] for item in response.json()['members']], [second, first])
        self.assertEqual(response.json()['members'][0]['name'], '成员二')
        self.assertEqual(response.json()['mode'], 'delegate')
        chat = self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [first], 'mode': 'group_chat'}).json()
        self.assertEqual(chat['mode'], 'group_chat')
        # 不传 mode 时保留原来的协作方式。
        self.assertEqual(self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [second, first]}).json()['mode'], 'group_chat')
        self.assertEqual(self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [], 'mode': 'vote'}).status_code, 422)
        self.assertEqual(self.team(lead), [second, first])
        self.client.put(f'/api/agents/{lead}/team', json={'member_ids': ['timesheet_assistant']})
        self.assertEqual(self.team(lead), ['timesheet_assistant'])

        put = lambda ids: self.client.put(f'/api/agents/{lead}/team', json={'member_ids': ids})
        self.assertEqual(put([lead]).status_code, 422)
        self.assertEqual(put(['missing']).status_code, 404)
        self.assertEqual(put([self.create_agent(f'成员{index}') for index in range(6)]).status_code, 422)
        self.client.put(f'/api/agents/{first}/archived', json={'archived': True})
        self.assertEqual(put([first]).status_code, 409)
        self.assertEqual(self.team(lead), ['timesheet_assistant'])
        self.assertEqual(self.client.get('/api/agents/missing/team').status_code, 404)
        self.assertEqual(self.client.put('/api/agents/missing/team', json={'member_ids': []}).status_code, 404)
        self.assertEqual(put([]).json()['members'], [])

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

    def test_deleting_a_member_or_lead_removes_team_rows_and_delegated_conversations(self):
        lead, member, other = self.create_agent('负责人'), self.create_agent('成员'), self.create_agent('另一个成员')
        self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [member, other]})
        parent = self.create_conversation(lead)
        member_child, other_child = self.delegate(parent, member), self.delegate(parent, other)

        self.assertEqual(self.client.delete(f'/api/agents/{member}').json(), {'deleted': True, 'conversations': 1})
        self.assertEqual(self.team(lead), [other])
        self.assertFalse(self.services.store.exists(member_child))
        self.assertEqual([item['child_conversation_id'] for item in self.client.get(f'/api/conversations/{parent}/delegations').json()],
                         [other_child])

        self.client.put(f'/api/agents/{other}/team', json={'member_ids': [lead]})
        self.client.put(f'/api/agents/{lead}/team', json={'member_ids': [other], 'mode': 'group_chat'})
        self.assertEqual(self.client.delete(f'/api/agents/{lead}').json(), {'deleted': True, 'conversations': 2})
        self.assertFalse(self.services.store.exists(other_child))
        self.assertEqual(self.team(other), [])
        with self.services.store.database.connection() as connection:
            self.assertIsNone(connection.execute('SELECT 1 FROM agent_team_members').fetchone())
            self.assertIsNone(connection.execute('SELECT 1 FROM agent_team_settings WHERE lead_agent_id = ?', (lead,)).fetchone())


if __name__ == '__main__':
    unittest.main()

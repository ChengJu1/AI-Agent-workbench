"""Archiving and deleting conversations and agents; synthetic data only."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services


class ArchiveDeleteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / 'synthetic.db')
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(settings=self.settings, services=self.services))
        self.addCleanup(self.client.close)

    def create_agent(self):
        response = self.client.post('/api/agents', json={'name': '合成助理', 'description': '测试用', 'system_prompt': '回答问题。',
                                                         'platform_capabilities': ['files']})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_conversation(self, agent_id):
        response = self.client.post('/api/conversations', json={'agent_id': agent_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['conversation_id']

    def conversations(self, agent_id):
        return {item['id']: item for item in self.client.get(f'/api/agents/{agent_id}/conversations').json()}

    def agents(self):
        return {item['id']: item for item in self.client.get('/api/agents').json()}

    def test_conversation_archive_is_reversible_and_keeps_messages(self):
        agent = self.create_agent()['id']
        cid = self.create_conversation(agent)
        self.services.store.add_message(cid, 'user', '合成问题')
        listed = self.conversations(agent)[cid]
        self.assertEqual((listed['archived'], listed['read_only']), (False, False))

        self.assertEqual(self.client.put(f'/api/conversations/{cid}/archived', json={'archived': True}).json(), {'archived': True})
        self.assertTrue(self.conversations(agent)[cid]['archived'])
        self.assertEqual(len(self.client.get(f'/api/conversations/{cid}/messages').json()), 1)
        self.client.put(f'/api/conversations/{cid}/archived', json={'archived': False})
        self.assertFalse(self.conversations(agent)[cid]['archived'])

        self.assertEqual(self.client.put('/api/conversations/missing/archived', json={'archived': True}).status_code, 404)
        self.assertEqual(self.client.put(f'/api/conversations/{cid}/archived', json={}).status_code, 422)

    def test_deleting_an_archived_conversation_removes_its_archive_row(self):
        agent = self.create_agent()['id']
        cid = self.create_conversation(agent)
        self.client.put(f'/api/conversations/{cid}/archived', json={'archived': True})
        self.assertEqual(self.client.delete(f'/api/conversations/{cid}').status_code, 200)
        self.assertEqual(self.conversations(agent), {})
        with self.services.store.database.connection() as connection:
            self.assertIsNone(connection.execute('SELECT 1 FROM archived_conversations').fetchone())

    def test_archived_agent_is_listed_as_archived_and_cannot_start_conversations(self):
        agent = self.create_agent()['id']
        kept = self.create_conversation(agent)
        archived = self.client.put(f'/api/agents/{agent}/archived', json={'archived': True})
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json()['archived'])
        self.assertTrue(self.agents()[agent]['archived'])
        self.assertIn(kept, self.conversations(agent))
        self.assertEqual(self.client.post('/api/conversations', json={'agent_id': agent}).status_code, 409)

        self.client.put(f'/api/agents/{agent}/archived', json={'archived': False})
        self.assertFalse(self.agents()[agent]['archived'])
        self.create_conversation(agent)
        self.assertEqual(self.client.put('/api/agents/missing/archived', json={'archived': True}).status_code, 404)

    def test_builtin_agents_can_be_archived_but_not_deleted(self):
        builtin = 'timesheet_assistant'
        self.assertFalse(self.agents()[builtin]['deletable'])
        self.assertTrue(self.create_agent()['deletable'])
        self.assertEqual(self.client.delete(f'/api/agents/{builtin}').status_code, 409)
        self.assertEqual(self.client.put(f'/api/agents/{builtin}/archived', json={'archived': True}).status_code, 200)
        self.assertTrue(self.agents()[builtin]['archived'])

    def test_deleting_an_agent_removes_its_conversations_bindings_and_archive_flag(self):
        agent = self.create_agent()['id']
        other = self.create_agent()['id']
        first, second = self.create_conversation(agent), self.create_conversation(agent)
        survivor = self.create_conversation(other)
        self.services.store.add_message(first, 'user', '合成问题')
        self.client.put(f'/api/conversations/{second}/archived', json={'archived': True})
        self.client.put(f'/api/agents/{agent}/archived', json={'archived': True})
        self.services.registry.bind_platform(agent, ['files'])

        response = self.client.delete(f'/api/agents/{agent}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'deleted': True, 'conversations': 2})
        self.assertNotIn(agent, self.agents())
        self.assertEqual(self.client.get(f'/api/agents/{agent}/conversations').status_code, 404)
        self.assertIn(survivor, self.conversations(other))
        with self.services.store.database.connection() as connection:
            for table, column in [('conversations', 'agent_id'), ('archived_agents', 'agent_id'),
                                  ('agent_platform_capabilities', 'agent_id'), ('custom_agents', 'id')]:
                self.assertIsNone(connection.execute(f'SELECT 1 FROM {table} WHERE {column} = ?', (agent,)).fetchone(), table)
            self.assertIsNone(connection.execute('SELECT 1 FROM archived_conversations').fetchone())
        self.assertEqual(self.client.delete(f'/api/agents/{agent}').status_code, 404)

    def test_agent_delete_is_refused_while_one_of_its_conversations_is_replying(self):
        agent = self.create_agent()['id']
        busy = self.create_conversation(agent)
        idle = self.create_conversation(agent)
        self.services.conversations._active[busy] = object()
        self.assertEqual(self.client.delete(f'/api/agents/{agent}').status_code, 409)
        self.assertEqual(set(self.conversations(agent)), {busy, idle})
        self.assertNotIn(idle, self.services.conversations._active)
        self.services.conversations._active.pop(busy)
        self.assertEqual(self.client.delete(f'/api/agents/{agent}').status_code, 200)


if __name__ == '__main__':
    unittest.main()

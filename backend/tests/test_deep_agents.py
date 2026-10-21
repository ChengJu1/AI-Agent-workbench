"""Deterministic Deep Agents graph tests. All models and data are synthetic."""
import asyncio
import json
from contextlib import aclosing
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import Field

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.runtime import RuntimeContext
from app.runtime.deep_agents import DeepAgentsRuntime
from app.runtime.read_only_backend import SessionReadOnlyBackend
from app.storage.database import Database
from app.models.tracking import WorkItemSave, TrackingDefinition


class FakeDeepModel(FakeListChatModel):
    seen: list = Field(default_factory=list)
    tool_names: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.tool_names = [tool.name for tool in tools]
        return self

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class ToolModel(FakeDeepModel):
    action: str = 'read_file'
    arguments: dict = Field(default_factory=lambda: {'file_path': '/synthetic.txt', 'offset': 0, 'limit': 1})
    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not any(message.type == 'tool' for message in messages):
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[{
                'name': self.action, 'args': json.dumps(self.arguments), 'id': 'synthetic-call', 'index': 0,
            }], chunk_position='last'))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content='已核对', chunk_position='last',
                usage_metadata={'input_tokens': 20, 'output_tokens': 3, 'total_tokens': 23}))


class DeepAgentsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.settings = Settings(database_path=self.directory / 'synthetic.db', deepagents_enabled=True)
        self.services = build_services(self.settings)
        self.runtime = self.services.deep_agents
        self.agent = self.services.registry.get_agent('timesheet_assistant')
        self.cid = self.services.conversations.create(self.agent.id, 'deep_agents')
        self.model = FakeDeepModel(responses=['模拟回答'])
        self.runtime.model_factory = lambda: self.model
        self.client = TestClient(create_app(settings=self.settings, services=self.services))
        self.addCleanup(self.client.close)

    def send(self, content='合成请求', services=None, cid=None):
        services, cid = services or self.services, cid or self.cid
        async def run():
            prepared = services.conversations.prepare(cid, content)
            return [event async for event in services.conversations.stream(cid, content, prepared)]
        # A real model call is a test failure even if credentials happen to exist.
        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real model forbidden')):
            return asyncio.run(run())

    def test_streams_text_and_only_read_only_tools_are_exposed(self):
        events = self.send()
        self.assertEqual(''.join(event['content'] for event in events if event['type'] == 'delta'), '模拟回答')
        self.assertEqual(events[-1], {'type': 'done'})
        self.assertEqual(set(self.model.tool_names), {'ls', 'read_file', 'mcp__timesheet_cli__query_calendar', 'mcp__timesheet_cli__draft_timesheet', 'mcp__timesheet_cli__submit_timesheet'})
        usage = next(event['usage'] for event in events if event['type'] == 'usage')
        self.assertEqual(usage['runtime'], 'deep_agents')
        self.assertEqual(usage['model_calls'], 1)
        self.assertIsNotNone(usage['first_token_ms'])
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['content'], '模拟回答')
        self.assertNotIn(self.cid, self.services.conversations._active)

    def test_restart_restores_exact_thread_and_injects_fresh_context(self):
        self.send('第一轮约定')
        fresh = build_services(self.settings)
        second = FakeDeepModel(responses=['继续回答'])
        fresh.deep_agents.model_factory = lambda: second
        events = self.send('第二轮请求', fresh)
        self.assertEqual(events[-1]['type'], 'done')
        history = second.seen[0]
        self.assertIn('第一轮约定', [message.content for message in history])
        self.assertIn('模拟回答', [message.content for message in history])
        self.assertIn('第二轮请求', [message.content for message in history])
        self.assertEqual(sum(message.content == '第二轮请求' for message in history), 1)
        self.assertIn('本轮结构化任务状态', history[0].content)
        with SqliteSaver.from_conn_string(str(self.settings.checkpoint_path)) as saver:
            saved = saver.get_tuple({'configurable': {'thread_id': self.cid}})
            self.assertIsNotNone(saved)
            self.assertEqual(saved.config['configurable']['thread_id'], self.cid)

    def test_delete_cleans_checkpoint_writes_artifacts_and_conversation_only(self):
        self.send()
        artifact = self.runtime.conversation_directory(self.cid) / 'synthetic.txt'
        artifact.write_text('合成内容')
        other_id = self.services.conversations.create(self.agent.id, 'deep_agents')
        self.send(cid=other_id)
        other_artifact = self.runtime.conversation_directory(other_id) / 'keep.txt'
        other_artifact.write_text('保留')
        response = self.client.delete(f'/api/conversations/{self.cid}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.services.store.exists(self.cid))
        self.assertFalse(artifact.parent.exists())
        self.assertTrue(other_artifact.exists())
        with sqlite3.connect(self.settings.checkpoint_path) as connection:
            for table in ('checkpoints', 'writes'):
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table} WHERE thread_id=?', (self.cid,)).fetchone()[0], 0)
            self.assertGreater(connection.execute('SELECT COUNT(*) FROM checkpoints WHERE thread_id=?', (other_id,)).fetchone()[0], 0)

    def test_delete_removes_related_records_without_foreign_key_failures(self):
        item = self.services.tracking.items.save(self.cid, self.agent.id, WorkItemSave(
            key='synthetic', title='合成事项', target_url='http://synthetic.invalid/'))
        self.services.tracking.items.begin_attempt(self.cid, self.agent.id, 'http://synthetic.invalid/')
        action_id = self.services.tool_store.create_pending_action(self.cid, self.agent.id, 'workbench_platform',
            'browser_actions', {'url': 'http://synthetic.invalid/', 'work_item_id': item['id']})
        task = self.services.tracking.store.create(self.cid, self.agent.id, TrackingDefinition(
            title='合成检查', url='http://synthetic.invalid/', anchor='synthetic', record_id='run_' + action_id,
            rules=[{'status': 'done', 'keywords': ['synthetic']}]))
        with self.services.store.database.connection() as connection:
            connection.execute("INSERT INTO tracking_checks(task_id,previous_status,status,outcome,evidence) VALUES (?,'','','synthetic','{}')", (task['id'],))
        self.assertEqual(self.client.delete(f'/api/conversations/{self.cid}').status_code, 200)
        with self.services.store.database.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ('work_items', 'work_item_events', 'work_item_actions', 'work_item_attempts', 'tracking_tasks', 'tracking_checks', 'execution_records', 'pending_actions'):
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_disabled_flag_rejects_deep_creation_and_turn_without_new_storage(self):
        disabled = build_services(Settings(database_path=self.directory / 'disabled.db'))
        client = TestClient(create_app(services=disabled))
        self.addCleanup(client.close)
        response = client.post('/api/conversations', json={'agent_id': self.agent.id, 'runtime': 'deep_agents'})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(disabled.deep_agents.settings.checkpoint_path.exists())
        # Existing Deep Agents conversations remain readable/deletable while disabled.
        fresh = build_services(Settings(database_path=self.settings.database_path))
        existing_client = TestClient(create_app(services=fresh))
        self.addCleanup(existing_client.close)
        response = existing_client.post(f'/api/conversations/{self.cid}/messages/stream', json={'content': '不能执行'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(fresh.store.get_messages(self.cid), [])
        self.assertEqual(existing_client.delete(f'/api/conversations/{self.cid}').status_code, 200)

    def test_runtime_is_immutable_and_default_is_claude(self):
        default = self.client.post('/api/conversations', json={'agent_id': self.agent.id}).json()['conversation_id']
        self.assertEqual(self.services.store.get_runtime(default), 'claude_sdk')
        with self.services.store.database.connection() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE conversations SET runtime='claude_sdk' WHERE id=?", (self.cid,))
        self.assertEqual(self.services.store.get_runtime(self.cid), 'deep_agents')
        listing = self.services.store.list_conversations(self.agent.id)
        self.assertEqual({item['runtime'] for item in listing}, {'claude_sdk', 'deep_agents'})

    def test_old_database_migrates_existing_conversations_to_claude(self):
        path = self.directory / 'legacy.db'
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,created_at TEXT)')
            connection.execute("INSERT INTO conversations VALUES ('old','fake','2026-10-21')")
        Database(path).initialize()
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("SELECT runtime FROM conversations WHERE id='old'").fetchone()[0], 'claude_sdk')
        Database(path).initialize()

    def test_read_tool_events_contain_no_file_content_and_failure_is_reported(self):
        directory = self.runtime.conversation_directory(self.cid)
        directory.mkdir(parents=True)
        (directory / 'synthetic.txt').write_text('PRIVATE_SYNTHETIC_TEXT\n第二行\n')
        model = ToolModel(responses=['unused'])
        self.runtime.model_factory = lambda: model
        events = self.send()
        tool_events = [event for event in events if event['type'].startswith('tool_')]
        self.assertEqual([event['type'] for event in tool_events], ['tool_started', 'tool_finished'])
        self.assertTrue(tool_events[-1]['success'])
        self.assertNotIn('PRIVATE_SYNTHETIC_TEXT', str(tool_events))
        self.assertIn('PRIVATE_SYNTHETIC_TEXT', str(model.seen[-1]))
        self.assertNotIn('第二行', str(model.seen[-1]))

    def test_forbidden_task_write_and_execute_tools_are_not_dispatchable(self):
        for action, arguments in [('task', {'description': 'synthetic', 'subagent_type': 'general-purpose'}),
                                   ('write_file', {'file_path': '/forbidden.txt', 'content': 'synthetic'}),
                                   ('edit_file', {'file_path': '/forbidden.txt', 'old_string': 'a', 'new_string': 'b'}),
                                   ('execute', {'command': 'echo synthetic'})]:
            with self.subTest(action=action):
                cid = self.services.conversations.create(self.agent.id, 'deep_agents')
                model = ToolModel(responses=['unused'], action=action, arguments=arguments)
                self.runtime.model_factory = lambda: model
                with patch('subprocess.Popen', side_effect=AssertionError('No execution')):
                    events = self.send(cid=cid)
                finished = next(event for event in events if event['type'] == 'tool_finished')
                self.assertFalse(finished['success'])
                self.assertEqual(set(model.tool_names), {'ls', 'read_file', 'mcp__timesheet_cli__query_calendar', 'mcp__timesheet_cli__draft_timesheet', 'mcp__timesheet_cli__submit_timesheet'})
                self.assertEqual(list(self.runtime.conversation_directory(cid).iterdir()), [])

    def test_ungranted_business_capability_is_not_advertised_or_executed(self):
        model = ToolModel(responses=['unused'], action='mcp__workbench_platform__browser_prepare_actions',
                          arguments={'session_id': 'browser_' + '1' * 32, 'snapshot_id': 'synthetic',
                                     'operations': [{'kind': 'click', 'element_id': 'e_1'}]})
        self.runtime.model_factory = lambda: model
        with patch.object(self.services.platform, 'execute', side_effect=AssertionError('Unauthorized dispatch')):
            events = self.send()
        self.assertNotIn(model.action, model.tool_names)
        self.assertFalse(next(e['success'] for e in events if e['type'] == 'tool_finished'))
        self.assertEqual(self.services.tool_store.get_pending_actions(self.cid), [])
        self.assertEqual(self.services.tool_store.get_audit_logs(self.cid), [])

    def test_failed_read_emits_failure_without_exposing_return_text(self):
        self.runtime.model_factory = lambda: ToolModel(responses=['unused'], arguments={'file_path': '/missing.txt'})
        events = self.send()
        finished = next(event for event in events if event['type'] == 'tool_finished')
        self.assertFalse(finished['success'])
        self.assertNotIn('missing.txt', str(finished))

    def test_cancel_closes_sqlite_and_records_failure_without_done(self):
        async def run():
            prepared = self.services.conversations.prepare(self.cid, '取消测试')
            stream = self.services.conversations.stream(self.cid, '取消测试', prepared)
            self.assertEqual((await anext(stream))['type'], 'delta')
            await stream.aclose()
            self.assertNotIn(self.cid, self.services.conversations._active)
        asyncio.run(run())
        with self.services.store.database.connection() as connection:
            usage = json.loads(connection.execute('SELECT usage FROM runtime_usage WHERE conversation_id=?', (self.cid,)).fetchone()[0])
        self.assertEqual(usage['status'], 'failed')
        self.services.conversations.delete(self.cid)
        self.assertFalse(self.services.store.exists(self.cid))

    def test_executing_approval_prevents_deletion(self):
        action_id = self.services.tool_store.create_pending_action(self.cid, self.agent.id, 'timesheet_cli', 'submit_timesheet', {})
        self.services.tool_store.update_pending_action(action_id, 'executing')
        with patch.object(self.runtime, 'delete_conversation') as delete:
            self.assertEqual(self.client.delete(f'/api/conversations/{self.cid}').status_code, 409)
            delete.assert_not_called()

    def test_env_switch_and_independent_fields_are_explicit(self):
        with patch('app.config.load_dotenv'), patch.dict(os.environ, {
            'WORKBENCH_DEEPAGENTS_ENABLED': 'true', 'WORKBENCH_DEEPAGENTS_MODEL': 'independent-model',
            'WORKBENCH_DEEPAGENTS_API_KEY': 'independent-key', 'WORKBENCH_DEEPAGENTS_BASE_URL': 'https://synthetic.invalid',
            'WORKBENCH_DATABASE_PATH': str(self.directory / 'env.db'),
            'ANTHROPIC_MODEL': 'unrelated-model', 'ANTHROPIC_API_KEY': 'unrelated-key',
        }, clear=True):
            settings = Settings.from_env()
        self.assertTrue(settings.deepagents_enabled)
        self.assertEqual(settings.deepagents_model, 'independent-model')
        self.assertEqual(settings.deepagents_api_key, 'independent-key')
        self.assertEqual(settings.checkpoint_path, self.directory.resolve() / 'deepagents.db')
        self.assertEqual(settings.artifacts_directory, self.directory.resolve() / 'runtime-artifacts')

    def test_partial_failure_preserves_text_and_releases_lock(self):
        self.model.error_on_chunk_number = 2
        events = self.send()
        self.assertEqual(events[-1]['type'], 'error')
        self.assertNotIn('done', [event['type'] for event in events])
        self.assertEqual(self.services.store.get_messages(self.cid)[-1]['content'], '模拟')
        self.assertNotIn(self.cid, self.services.conversations._active)
        self.assertEqual(next(event['usage'] for event in events if event['type'] == 'usage')['status'], 'failed')

    def test_delete_is_rejected_while_reply_is_prepared(self):
        prepared = self.services.conversations.prepare(self.cid, '合成请求')
        try:
            self.assertEqual(self.client.delete(f'/api/conversations/{self.cid}').status_code, 409)
            self.assertTrue(self.services.store.exists(self.cid))
        finally:
            self.services.conversations.release(self.cid, prepared)

    def test_independent_model_configuration_never_uses_anthropic_credentials(self):
        settings = Settings(database_path=self.directory / 'independent.db', deepagents_enabled=True,
                            deepagents_api_key='synthetic-deep-key', deepagents_model='deepseek-v4-flash',
                            deepagents_base_url='https://synthetic.invalid/v1')
        runtime = DeepAgentsRuntime(settings, self.services.tool_store)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'different-secret', 'ANTHROPIC_BASE_URL': 'https://other.invalid'}):
            model = runtime._model()
        self.assertEqual(model.model_name, 'deepseek-v4-flash')
        self.assertEqual(model.api_key.get_secret_value(), 'synthetic-deep-key')
        self.assertEqual(str(model.api_base).rstrip('/'), 'https://synthetic.invalid/v1')
        self.assertNotIn('synthetic-deep-key', repr(settings))
        with self.assertRaises(ValueError):
            Settings(database_path=self.directory / 'same.db', deepagents_checkpoint_path=self.directory / 'same.db')
        legacy_name = Settings(database_path=self.directory / 'deepagents.db')
        self.assertFalse(legacy_name.deepagents_enabled)
        self.assertNotEqual(legacy_name.checkpoint_path, legacy_name.database_path)


class ReadOnlyBackendTests(unittest.TestCase):
    def test_path_traversal_sibling_and_symlink_cannot_read_other_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current, other = root / 'current', root / 'other'
            current.mkdir(); other.mkdir()
            (current / 'allowed.txt').write_text('第一行\n第二行\n')
            (other / 'private.txt').write_text('PRIVATE_OTHER_SESSION')
            (current / 'link').symlink_to(other, target_is_directory=True)
            backend = SessionReadOnlyBackend(current)
            self.assertEqual(backend.read('/allowed.txt', offset=1, limit=1).file_data['content'], '第二行\n')
            for path in ('../other/private.txt', '/link/private.txt', '/etc/passwd', '~/private.txt'):
                result = backend.read(path)
                self.assertIsNotNone(result.error)
                self.assertNotIn('PRIVATE_OTHER_SESSION', str(result))
            self.assertEqual([item['path'] for item in backend.ls('/').entries], ['/allowed.txt'])
            for method, arguments in [('write', ('/new.txt', 'x')), ('edit', ('/allowed.txt', 'a', 'b')), ('delete', ('/allowed.txt',))]:
                with self.assertRaises(NotImplementedError):
                    getattr(backend, method)(*arguments)
            self.assertEqual((current / 'allowed.txt').read_text(), '第一行\n第二行\n')

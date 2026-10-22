"""Synthetic-only acceptance for offload, readback, compaction and live task state."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from mcp.shared.memory import create_connected_server_and_client_session

from app.config import Settings
from app.container import build_services
from app.models.api import CreateAgentRequest
from app.kits.job_search.models import ApplicationSave
from app.kits.job_search.profiles import ProfileSave
from app.runtime.context_summary import WorkbenchSummarizationMiddleware
from app.runtime.read_only_backend import SessionReadOnlyBackend
from app.runtime.result_offload import ResultOffloader
from app.services.token_counter import TokenCounter
from test_deep_agents import FakeDeepModel


async def invoke_summary(middleware, messages):
    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.messages import AIMessage
    seen = []
    async def handler(request):
        seen.append(request.messages)
        return ModelResponse(result=[AIMessage(content='合成回复')])
    await middleware.awrap_model_call(ModelRequest(model=middleware.model, messages=messages,
        state={'messages': messages}, tools=[]), handler)
    return seen[0]


class ResultOffloadTests(unittest.TestCase):
    def test_large_json_is_redacted_bounded_and_readable_to_last_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy = ResultOffloader(temporary, '11111111-1111-1111-1111-111111111111', 4000)
            response = {'content': [{'type': 'text', 'text': json.dumps({'token': 'PRIVATE_SECRET',
                'email': 'synthetic@example.com', 'phone': '13812345678',
                'text': '合成资料' * 3000 + 'END_OF_SYNTHETIC_RESULT'})}], 'is_error': True,
                'structuredContent': {'token': 'PRIVATE_SECRET'}}
            result = asyncio.run(policy.transform('mcp__shared__read', response))
            self.assertTrue(result['is_error'])
            self.assertNotIn('structuredContent', result)
            reference = json.loads(result['content'][0]['text'])
            self.assertTrue(reference['offloaded'])
            self.assertLess(len(str(result)), 2000)
            backend = SessionReadOnlyBackend(policy.directory)
            offset, parts = 0, []
            while True:
                page = backend.read(reference['path'], offset, 3)
                self.assertIsNone(page.error)
                self.assertLessEqual(len(page.file_data['content']), 20000)
                parts.append(page.file_data['content'])
                if page.next_offset is None:
                    break
                offset = page.next_offset
            full = ''.join(parts)
            for secret in ('PRIVATE_SECRET', 'synthetic@example.com', '13812345678'):
                self.assertNotIn(secret, full)
                self.assertNotIn(secret, str(result))
            self.assertIn('END_OF_SYNTHETIC_RESULT', full)
            self.assertIn('138****5678', full)
            self.assertEqual(policy.metrics()['offloaded_results'], 1)
            self.assertEqual(asyncio.run(policy.transform('read_file', response)), response)

    def test_small_result_is_unchanged_and_symlink_write_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = ResultOffloader(root, '11111111-1111-1111-1111-111111111111', 100)
            response = {'content': [{'type': 'text', 'text': 'small'}]}
            self.assertEqual(asyncio.run(policy.transform('shared', response)), response)
            other = root / 'other'
            other.mkdir()
            policy.directory.symlink_to(other, target_is_directory=True)
            result = asyncio.run(policy.transform('shared', {'content': [{'type': 'text', 'text': 'SYNTHETIC' * 100}]}))
            self.assertTrue(result['is_error'])
            self.assertEqual(list(other.iterdir()), [])

    def test_files_larger_than_four_megabytes_can_be_read_in_bounded_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'large.txt'
            path.write_text(('x' * 1000 + '\n') * 4100 + 'TAIL_MARKER')
            page = SessionReadOnlyBackend(temporary).read('/large.txt', 4095, 100)
            self.assertIsNone(page.error)
            self.assertIn('TAIL_MARKER', page.file_data['content'])
            self.assertLess(len(page.file_data['content']), 20000)


class ContextManagementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def send(self, services, cid, text):
        async def run():
            prepared = services.conversations.prepare(cid, text)
            return [event async for event in services.conversations.stream(cid, text, prepared)]
        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real model forbidden')):
            return asyncio.run(run())

    def test_actual_graph_summary_preserves_goal_live_ids_versions_and_pending(self):
        settings = Settings(database_path=self.root / 'synthetic.db',
                            deepagents_summary_trigger_tokens=100000, deepagents_summary_trigger_messages=6,
                            deepagents_summary_keep_messages=2)
        services = build_services(settings)
        agent = services.registry.create(CreateAgentRequest(name='合成任务', description='合成', system_prompt='核对', platform_capabilities=['applications']))
        cid = services.conversations.create(agent.id)
        application = services.kits['applications'].applications.save(ApplicationSave(company='合成公司', position='合成岗位'))
        profile = services.kits['applications'].profiles.save(ProfileSave(name='合成档案', data={}))
        pending = services.tool_store.create_pending_action(cid, agent.id, 'workbench_platform', 'browser_actions', {})
        model = FakeDeepModel(responses=['合成回复'])
        summary_model = FakeListChatModel(responses=['用户目标：准备合成申请。硬性要求：不得提交。后续纠正：只考虑上海。待办：核对资料。待确认操作尚未执行。'])
        services.deep_agents.model_factory = lambda: model
        services.deep_agents.summary_model_factory = lambda: summary_model
        goal = '准备合成申请。硬性要求：不得提交。'
        summary_events = []
        for index, text in enumerate([goal, '后续纠正：只考虑上海。', '填充合成过程 ' * 200, '继续核对']):
            if index == 3:
                services.kits['applications'].profiles.save(ProfileSave(name='合成档案', data={}, expected_version=1), profile['id'])
            events = self.send(services, cid, text)
            self.assertEqual(events[-1]['type'], 'done')
            summary_events.append(next(e['usage']['context_management'] for e in events if e['type'] == 'usage'))
        self.assertGreaterEqual(sum(event['summaries_completed'] for event in summary_events), 1)
        final = model.seen[-1]
        self.assertIn('不得提交', str(final))
        self.assertIn('只考虑上海', str(final))
        state = next(message.content for message in final if str(message.content).startswith('【平台状态'))
        self.assertIn(application['id'], state)
        self.assertIn(profile['id'], state)
        self.assertIn('"latest_version": 2', state)
        self.assertIn(pending, state)
        self.assertIn('只考虑上海', state)
        self.assertEqual(services.tool_store.get_pending_action(pending)['status'], 'pending')
        self.assertEqual(len(services.store.get_messages(cid)), 8)
        self.assertFalse(any('用户目标：' in e.get('content', '') for e in events if e['type'] == 'delta'))
        fresh = build_services(settings)
        fresh_model = FakeDeepModel(responses=['重启后继续核对'])
        fresh.deep_agents.model_factory = lambda: fresh_model
        fresh.deep_agents.summary_model_factory = lambda: summary_model
        restarted = self.send(fresh, cid, '重启后继续')
        self.assertEqual(restarted[-1]['type'], 'done')
        self.assertIn('不得提交', str(fresh_model.seen[0]))
        self.assertIn('只考虑上海', str(fresh_model.seen[0]))
        self.assertIn(pending, next(m.content for m in fresh_model.seen[0] if str(m.content).startswith('【平台状态')))
        self.assertEqual(len(fresh.store.get_messages(cid)), 10)

    def test_token_trigger_uses_real_tokenizer_and_preserves_tool_pairs(self):
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        settings = Settings(deepagents_summary_trigger_tokens=100, deepagents_summary_trigger_messages=100,
                            deepagents_summary_keep_messages=2)
        middleware = WorkbenchSummarizationMiddleware(FakeListChatModel(responses=['目标和限制保持。']), settings, directory=self.root)
        messages = [HumanMessage(content='目标：不得提交。' * 100),
            AIMessage(content='', tool_calls=[{'name': 'shared', 'args': {}, 'id': 'call'}]),
            ToolMessage(content='合成工具结果', tool_call_id='call'), HumanMessage(content='继续')]
        serialized = json.dumps([{'role': m.type, 'content': m.content, 'tool_calls': getattr(m, 'tool_calls', [])} for m in messages], ensure_ascii=False)
        self.assertEqual(middleware.count_messages(messages), TokenCounter(settings.deepagents_model).count(serialized))
        result = asyncio.run(invoke_summary(middleware, messages))
        self.assertIsNotNone(result)
        preserved = result[1:]
        tool_ids = {m.tool_call_id for m in preserved if m.type == 'tool'}
        call_ids = {call['id'] for m in preserved if m.type == 'ai' for call in m.tool_calls}
        self.assertEqual(tool_ids, call_ids)

    def test_summary_failure_keeps_original_history_and_reports_no_success(self):
        from langchain_core.messages import HumanMessage, AIMessage
        settings = Settings(deepagents_summary_trigger_messages=3, deepagents_summary_keep_messages=1)
        middleware = WorkbenchSummarizationMiddleware(FakeListChatModel(responses=['']), settings, directory=self.root)
        messages = [HumanMessage(content='不得提交'), AIMessage(content='待确认'), HumanMessage(content='继续')]
        with self.assertRaises(ValueError):
            asyncio.run(invoke_summary(middleware, messages))
        self.assertEqual([m.content for m in messages], ['不得提交', '待确认', '继续'])
        self.assertEqual(middleware.metrics['summaries_completed'], 0)

    def test_context_settings_validate_bounds(self):
        for values in ({'tool_result_offload_chars': 0}, {'deepagents_summary_trigger_tokens': True},
                       {'deepagents_summary_keep_messages': 80, 'deepagents_summary_trigger_messages': 80}):
            with self.assertRaises(ValueError):
                Settings(**values)
        with patch('app.config.load_dotenv'), patch.dict(os.environ, {
            'WORKBENCH_TOOL_RESULT_OFFLOAD_CHARS': '5000',
            'WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_TOKENS': '12000', 'WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_MESSAGES': '40',
            'WORKBENCH_DEEPAGENTS_SUMMARY_KEEP_MESSAGES': '8'}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.tool_result_offload_chars, 5000)
        self.assertEqual(settings.deepagents_summary_trigger_tokens, 12000)
        self.assertEqual(settings.deepagents_summary_trigger_messages, 40)
        self.assertEqual(settings.deepagents_summary_keep_messages, 8)

    def test_unsupported_tokenizer_has_message_trigger_without_character_guess(self):
        from langchain_core.messages import HumanMessage, AIMessage
        settings = Settings(deepagents_model='unsupported-synthetic-model', deepagents_summary_trigger_messages=3,
                            deepagents_summary_keep_messages=1)
        middleware = WorkbenchSummarizationMiddleware(FakeListChatModel(responses=['保留目标。']), settings, directory=self.root)
        messages = [HumanMessage(content='a' * 1000), AIMessage(content='合成'), HumanMessage(content='继续')]
        self.assertEqual(middleware.count_messages(messages), 0)
        self.assertIsNotNone(asyncio.run(invoke_summary(middleware, messages)))
        self.assertIsNone(middleware.metrics['history_tokens_before_summary'])

    def test_task_state_reloads_file_versions_and_never_includes_other_conversations(self):
        services = build_services(Settings(database_path=self.root / 'synthetic.db'))
        agent = services.registry.create(CreateAgentRequest(name='合成附件', description='合成', system_prompt='核对', platform_capabilities=['files']))
        cid = services.conversations.create(agent.id)
        other = services.conversations.create(agent.id)
        first = services.platform.files.upload(cid, 'synthetic.txt', b'SYNTHETIC')
        private = services.platform.files.upload(other, 'other.txt', b'OTHER_SYNTHETIC')
        builder = services.conversations.task_context
        state = builder.build_task_context(cid, agent)
        self.assertIn(first['id'], state)
        self.assertNotIn(private['id'], state)
        with services.store.database.connection() as connection:
            connection.execute('UPDATE conversation_files SET version=2 WHERE id=?', (first['id'],))
        current = builder.build_task_context(cid, agent)
        self.assertIn('"version": 2', current)
        restricted = agent.model_copy(update={'platform_capabilities': []})
        self.assertNotIn(first['id'], builder.build_task_context(cid, restricted))

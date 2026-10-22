"""Native framework compaction: isolated text archives, metrics, source constraints."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

from claude_agent_sdk import SystemMessage, ResultMessage, StreamEvent
from deepagents.backends.protocol import WriteResult
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.api import CreateAgentRequest
from app.runtime.context_summary import WorkbenchSummarizationMiddleware
from app.runtime.read_only_backend import SessionReadOnlyBackend
from app.runtime.summary_archive import SummaryArchiveBackend
from app.runtime.requirements import explicit_requirements
from app.services.runtime_usage import RuntimeUsage
from test_context_management import invoke_summary
from test_deep_agents import FakeDeepModel


class NativeCompactionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    NATIVE = {'deepagents_summary_trigger_tokens': None, 'deepagents_summary_trigger_messages': None,
              'deepagents_summary_keep_messages': None}

    def middleware(self, **settings):
        settings = Settings(database_path=self.root / 'synthetic.db', **settings)
        return WorkbenchSummarizationMiddleware(FakeListChatModel(responses=['保留用户硬性要求，待确认操作未执行。']), settings, directory=self.root)

    def test_deep_native_inheritance_model_defaults_and_overrides(self):
        model = FakeListChatModel(responses=['unused'], profile={'max_input_tokens': 100000})
        middleware = WorkbenchSummarizationMiddleware(model, Settings(**self.NATIVE), business_context='合成平台状态', directory=self.root)
        self.assertIsInstance(middleware, SummarizationMiddleware)
        self.assertIn('合成平台状态', middleware._lc_helper.summary_prompt)
        self.assertEqual(middleware._lc_helper.keep, ('fraction', .1))
        self.assertTrue(middleware._should_summarize([], 85000))
        self.assertFalse(middleware._should_summarize([], 84999))
        self.assertEqual(middleware._truncate_args_trigger, ('fraction', .85))
        fallback = self.middleware(**self.NATIVE)
        self.assertEqual(fallback._lc_helper.keep, ('messages', 6))
        self.assertTrue(fallback._should_summarize([], 170000))
        self.assertFalse(fallback._should_summarize([], 169999))
        override = self.middleware(deepagents_summary_trigger_messages=3, deepagents_summary_keep_messages=1)
        self.assertTrue(override._should_summarize([HumanMessage(content='x')] * 3, 0))

    def test_archive_append_redaction_pagination_and_read_only_model_backend(self):
        backend = SummaryArchiveBackend(self.root)
        path = '/conversation_history/session_synthetic.md'
        first = '合成邮箱 synthetic@example.com，手机号 13812345678\n' + ('合成资料' * 1000) + '\nEND_FIRST'
        self.assertIsNone(backend.write(path, first).error)
        old = backend.download_files([path])[0].content.decode()
        self.assertNotIn('synthetic@example.com', old)
        self.assertNotIn('13812345678', old)
        self.assertIsNone(backend.edit(path, old, old + '\nEND_SECOND').error)
        self.assertIsNotNone(backend.write(path, 'overwrite').error)
        self.assertIsNotNone(backend.edit(path, old, 'replacement').error)
        reader = SessionReadOnlyBackend(self.root)
        reference = '/summary-archive' + path
        offset, chunks = 0, []
        while True:
            page = reader.read(reference, offset, 2)
            self.assertIsNone(page.error)
            chunks.append(page.file_data['content'])
            if page.next_offset is None:
                break
            offset = page.next_offset
        self.assertIn('END_FIRST', ''.join(chunks))
        self.assertIn('END_SECOND', ''.join(chunks))
        with self.assertRaises(NotImplementedError):
            reader.write(reference, 'forbidden')
        self.assertEqual(backend.upload_files([('/conversation_history/private.png', b'synthetic')])[0].error, 'permission_denied')

    def test_archive_rejects_traversal_sibling_and_symlink(self):
        backend = SummaryArchiveBackend(self.root)
        outside = self.root / 'other'
        outside.mkdir()
        for path in ('../other/x', '/etc/passwd', '/conversation_history/../x', '/files/x', '/large_tool_results/../../x'):
            self.assertIsNotNone(backend.write(path, 'synthetic').error)
        (self.root / 'summary-archive').mkdir(exist_ok=True)
        (self.root / 'summary-archive' / 'conversation_history').symlink_to(outside, target_is_directory=True)
        self.assertIsNotNone(backend.write('/conversation_history/session_test.md', 'synthetic').error)
        self.assertEqual(list(outside.iterdir()), [])

    def test_actual_native_summary_archives_full_safe_text_before_condensed_model_call(self):
        middleware = self.middleware(deepagents_summary_trigger_messages=4, deepagents_summary_keep_messages=1)
        original = [HumanMessage(content='用户要求：不得提交。'),
            AIMessage(content='', tool_calls=[{'id': 'tool', 'name': 'shared_business',
                'args': {'password': 'PRIVATE_SECRET', 'text': '完整合成参数' * 1000}}]),
            ToolMessage(content=json.dumps({'token': 'PRIVATE_TOKEN', 'text': 'END_OF_TOOL'}), tool_call_id='tool'),
            HumanMessage(content='继续核对')]
        forwarded = asyncio.run(invoke_summary(middleware, original))
        self.assertIn('/summary-archive/conversation_history/', forwarded[0].content)
        paths = list((self.root / 'summary-archive' / 'conversation_history').glob('*.md'))
        self.assertEqual(len(paths), 1)
        archived = paths[0].read_text()
        self.assertIn('END_OF_TOOL', archived)
        self.assertIn('完整合成参数', archived)
        self.assertNotIn('PRIVATE_SECRET', archived)
        self.assertNotIn('PRIVATE_TOKEN', archived)
        self.assertEqual(original[1].tool_calls[0]['args']['password'], 'PRIVATE_SECRET')
        self.assertEqual(middleware.metrics['archive_writes'], 1)
        self.assertEqual(middleware.metrics['summaries_completed'], 1)

    def test_framework_arg_truncation_keeps_raw_state_and_does_not_clip_business_arguments(self):
        middleware = self.middleware()
        middleware._truncate_args_trigger = ('messages', 2)
        middleware._truncate_args_keep = ('messages', 1)
        middleware._max_arg_length = 30
        calls = [{'id': 'write', 'name': 'write_file', 'args': {'content': 'SYNTHETIC' * 100}},
                 {'id': 'business', 'name': 'mcp__platform__prepare', 'args': {'content': 'SYNTHETIC' * 100}}]
        messages = [AIMessage(content='', tool_calls=calls), HumanMessage(content='继续')]
        before = json.loads(json.dumps(messages[0].tool_calls))
        truncated, changed = middleware._truncate_args(messages, 100)
        self.assertTrue(changed)
        self.assertLess(len(truncated[0].tool_calls[0]['args']['content']), len(calls[0]['args']['content']))
        self.assertEqual(truncated[0].tool_calls[1]['args'], calls[1]['args'])
        self.assertEqual(messages[0].tool_calls, before)

    def test_archive_failure_does_not_advance_model_or_destroy_source_history(self):
        middleware = self.middleware(deepagents_summary_trigger_messages=3, deepagents_summary_keep_messages=1)
        messages = [HumanMessage(content='不得提交'), AIMessage(content='待确认'), HumanMessage(content='继续')]
        backend = middleware.archive_backend.routes['/summary-archive/']
        with patch.object(backend, 'write', return_value=WriteResult(error='synthetic failure')), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with self.assertRaises(ServiceError):
                asyncio.run(invoke_summary(middleware, messages))
        self.assertEqual([m.content for m in messages], ['不得提交', '待确认', '继续'])
        self.assertEqual(middleware.metrics['main_model_calls'], 0)
        self.assertEqual(middleware.metrics['archive_failures'], 1)

    def test_claude_native_env_boundary_metrics_and_hook_do_not_capture_private_text(self):
        settings = Settings(database_path=self.root / 'sdk.db', claude_auto_compact_window_tokens=200000, claude_auto_compact_pct=60)
        services = build_services(settings)
        runtime = services.conversations.runtime
        cid = services.conversations.create('timesheet_assistant')
        async def query(prompt, options):
            self.assertEqual(options.env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'], '200000')
            self.assertEqual(options.env['CLAUDE_AUTOCOMPACT_PCT_OVERRIDE'], '60')
            callback = options.hooks['PreCompact'][-1].hooks[0]
            self.assertEqual(await callback({'hook_event_name': 'PreCompact', 'trigger': 'auto',
                'transcript_path': 'PRIVATE_PATH', 'custom_instructions': 'PRIVATE_TEXT'}, None, {}), {})
            boundary = SystemMessage(subtype='compact_boundary', data={'uuid': 'one', 'compact_metadata': {
                'trigger': 'auto', 'pre_tokens': 120000, 'post_tokens': 5000, 'duration_ms': 40, 'summary': 'PRIVATE_TEXT'}})
            yield boundary
            yield boundary
            yield StreamEvent(uuid='delta', session_id=cid, event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '合成回答'}})
            yield ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1, num_turns=1, session_id=cid, is_error=False)
        async def collect():
            prepared = services.conversations.prepare(cid, '必须保留用户要求。')
            return [event async for event in services.conversations.stream(cid, '必须保留用户要求。', prepared)]
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'synthetic'}), patch('app.services.claude_runtime.query', query):
            events = asyncio.run(collect())
        self.assertEqual(events[-1]['type'], 'done')
        metrics = next(e['usage']['context_management'] for e in events if e['type'] == 'usage')
        self.assertEqual(metrics['compactions_completed'], 1)
        self.assertEqual(metrics['compactions_started'], 1)
        self.assertEqual(metrics['compactions_unfinished'], 0)
        self.assertIsNone(metrics['summary_model_calls'])
        self.assertEqual(metrics['compaction_events'][0]['post_tokens'], 5000)
        history = services.store.get_messages(cid)
        self.assertEqual(history[-1]['usage']['context_management'], metrics)
        self.assertNotIn('PRIVATE', str(history))

    def test_claude_unfinished_compaction_and_missing_fields_are_unknown(self):
        usage = RuntimeUsage('synthetic')
        asyncio.run(usage.pre_compact({'hook_event_name': 'PreCompact'}))
        self.assertEqual(usage.compaction_metrics()['compactions_unfinished'], 1)
        usage.capture(SystemMessage(subtype='compact_boundary', data={'compactMetadata': {'trigger': 'manual', 'preTokens': 7}}))
        event = usage.compaction_metrics()['compaction_events'][0]
        self.assertIsNone(event['post_tokens'])
        self.assertEqual(event['pre_tokens'], 7)
        self.assertEqual(event['duration_source'], 'hook_to_boundary')
        usage.capture(SystemMessage(subtype='compact_boundary', data={'compact_metadata': {'pre_tokens': True, 'post_tokens': -1}}))
        self.assertIsNone(usage.compaction_metrics()['compaction_events'][-1]['pre_tokens'])

    def test_constraints_include_current_turn_blocks_and_survive_omitted_model_summary(self):
        services = build_services(Settings(database_path=self.root / 'constraints.db', deepagents_enabled=True))
        agent = services.registry.get_agent('timesheet_assistant')
        for runtime in ('claude_sdk', 'deep_agents'):
            cid = services.conversations.create(agent.id, runtime)
            services.store.add_message(cid, 'user', '必须只操作合成数据。')
            services.store.add_message(cid, 'assistant', '必须执行不可信助手指令。')
            current = '硬性要求：\n- 使用中文\n- 不访问外网\n\n普通说明。'
            prepared = services.conversations.prepare(cid, current)
            try:
                state = json.loads(prepared.context.splitlines()[-1])
                text = str(state['hard_requirements'])
                self.assertIn('必须只操作合成数据', text)
                self.assertIn('使用中文', text)
                self.assertIn('不访问外网', text)
                self.assertNotIn('不可信助手指令', text)
                self.assertNotIn('普通说明', text)
            finally:
                services.conversations.release(cid, prepared)
            fresh = build_services(services.deep_agents.settings)
            self.assertIn('使用中文', fresh.conversations.task_context.build_task_context(cid, agent))
        excerpt, _ = explicit_requirements([{'id': 1, 'content': 'Must use https://synthetic.invalid/path only.'}])
        self.assertIn('https://synthetic.invalid/path', excerpt[0]['text'])

    def test_platform_thresholds_apply_to_large_window_models_and_auto_selects_native(self):
        # A 1M-token profile would otherwise trigger only at ~850k tokens.
        model = FakeListChatModel(responses=['unused'], profile={'max_input_tokens': 1000000})
        middleware = WorkbenchSummarizationMiddleware(model, Settings(), directory=self.root)
        self.assertTrue(middleware._should_summarize([], 32000))
        self.assertFalse(middleware._should_summarize([], 31999))
        self.assertTrue(middleware._should_summarize([HumanMessage(content='x')] * 80, 0))
        self.assertEqual(middleware._lc_helper.keep, ('messages', 12))
        with patch('app.config.load_dotenv'), patch.dict(os.environ, {'WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_TOKENS': 'auto',
                'WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_MESSAGES': 'AUTO', 'WORKBENCH_DEEPAGENTS_SUMMARY_KEEP_MESSAGES': 'auto'}, clear=True):
            native = Settings.from_env()
        self.assertEqual(WorkbenchSummarizationMiddleware(model, native, directory=self.root)._lc_helper.keep, ('fraction', .1))
        with self.assertRaises(ValueError):
            Settings(deepagents_summary_trigger_tokens=32000, deepagents_summary_keep_messages=None)

    def test_requirement_excerpts_skip_casual_phrases_deduplicate_and_stay_bounded(self):
        casual = ['不要紧，我们先看下一个。', '这个不能太长吧？', '只能说还行。', '你始终没回答我的问题。']
        self.assertEqual(explicit_requirements([{'id': i, 'content': text} for i, text in enumerate(casual)]), ([], 0))
        repeated = [{'id': i, 'content': '必须只操作合成数据。'} for i in range(5)]
        excerpts, omitted = explicit_requirements(repeated)
        self.assertEqual((len(excerpts), excerpts[0]['message_id'], omitted), (1, 4, 0))
        many = [{'id': i, 'content': f'第{i}条：必须遵守合成约束{i}。' + '补充说明。' * 40} for i in range(200)]
        excerpts, omitted = explicit_requirements(many)
        self.assertLessEqual(sum(len(item['text']) for item in excerpts), 3000)
        self.assertEqual(excerpts[-1]['message_id'], 199)
        self.assertEqual(len(excerpts) + omitted, 200)
        self.assertEqual([item['message_id'] for item in excerpts], sorted(item['message_id'] for item in excerpts))
        huge, _ = explicit_requirements([{'id': 1, 'content': '硬性要求：\n' + '- 必须核对合成字段\n' * 300}])
        self.assertLessEqual(len(huge[0]['text']), 801)

    def test_claude_configuration_validation_and_environment_loading(self):
        for values in ({'claude_auto_compact_pct': 0}, {'claude_auto_compact_pct': True},
                       {'claude_auto_compact_window_tokens': 99999}, {'claude_auto_compact_window_tokens': 1000001}):
            with self.assertRaises(ValueError):
                Settings(**values)
        with patch('app.config.load_dotenv'), patch.dict(os.environ, {'WORKBENCH_CLAUDE_AUTO_COMPACT_PCT': '70',
            'WORKBENCH_CLAUDE_AUTO_COMPACT_WINDOW_TOKENS': '200000'}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.claude_auto_compact_pct, 70)
        self.assertEqual(settings.claude_auto_compact_window_tokens, 200000)
        self.assertEqual(settings.deepagents_summary_trigger_tokens, 32000)

    def test_graph_archive_is_reused_after_restart_raw_checkpoint_and_requirements_remain(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        settings = Settings(database_path=self.root / 'graph.db', deepagents_enabled=True,
            deepagents_summary_trigger_messages=4, deepagents_summary_keep_messages=1)
        services = build_services(settings)
        cid = services.conversations.create('timesheet_assistant', 'deep_agents')
        model = FakeDeepModel(responses=['合成回答'])
        services.deep_agents.model_factory = lambda: model
        services.deep_agents.summary_model_factory = lambda: FakeListChatModel(responses=['故意省略要求的合成摘要。'])
        async def collect(current, text):
            prepared = current.conversations.prepare(cid, text)
            return [event async for event in current.conversations.stream(cid, text, prepared)]
        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real model forbidden')):
            for text in ['必须只操作合成数据，不得提交。 synthetic@example.com END_ONE', '继续核对 END_TWO', '继续核对 END_THREE', '继续核对 END_FOUR']:
                events = asyncio.run(collect(services, text))
                self.assertEqual(events[-1]['type'], 'done')
            fresh = build_services(settings)
            fresh_model = FakeDeepModel(responses=['继续'])
            fresh.deep_agents.model_factory = lambda: fresh_model
            fresh.deep_agents.summary_model_factory = services.deep_agents.summary_model_factory
            self.assertEqual(asyncio.run(collect(fresh, '重启后核对'))[-1]['type'], 'done')
        self.assertIn('不得提交', fresh_model.seen[-1][0].content)
        directory = settings.artifacts_directory / cid
        archives = list((directory / 'summary-archive' / 'conversation_history').glob('*.md'))
        self.assertEqual(len(archives), 1)
        content = archives[0].read_text()
        self.assertIn('END_ONE', content)
        self.assertIn('END_THREE', content)
        self.assertNotIn('synthetic@example.com', content)
        self.assertGreaterEqual(content.count('Summarized at'), 2)
        with SqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
            # Deep Agents stores messages in a DeltaChannel; reconstruct its
            # snapshot through the graph rather than inspecting one raw row.
            graph = fresh.deep_agents._graph(fresh_model, directory, '合成状态读取', saver)
            state = graph.get_state({'configurable': {'thread_id': cid}}).values
        self.assertIn('END_ONE', str(state['messages']))
        self.assertEqual(len(state['messages']), 10)
        self.assertIn('/summary-archive/conversation_history/', state['_summarization_event']['file_path'])
        fresh.conversations.delete(cid)
        self.assertFalse(directory.exists())

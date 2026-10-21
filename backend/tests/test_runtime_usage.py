"""Deterministic telemetry and read-only reporting, using synthetic data only."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock, ToolResultBlock, UserMessage
from app.services.runtime_usage import RuntimeUsage
from app.services.token_counter import TokenCounter, load_tokenizer
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.usage_store import UsageStore

spec = importlib.util.spec_from_file_location('usage_report', Path(__file__).resolve().parents[1] / 'scripts/usage_report.py')
report_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_module)


class UsageTests(unittest.TestCase):
    def test_result_metrics_and_unique_tool_calls(self):
        with patch('app.services.runtime_usage.perf_counter', side_effect=[1, 1.25, 2]):
            tracker = RuntimeUsage('abcd')
            message = AssistantMessage(content=[ToolUseBlock(id='call1', name='fake', input={})], model='fake')
            tracker.capture(message)
            tracker.capture(message)
            tracker.capture(UserMessage(content=[ToolResultBlock(tool_use_id='call1', content='synthetic')]))
            tracker.delta()
            tracker.result = ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1,
                is_error=False, num_turns=2, session_id='fake', usage={
                    'input_tokens': 100, 'output_tokens': 20,
                    'cache_read_input_tokens': 80, 'cache_creation_input_tokens': 10})
            usage = tracker.snapshot()
        self.assertEqual(usage['input_tokens'], 100)
        self.assertEqual(usage['output_tokens'], 20)
        self.assertEqual(usage['cache_read_input_tokens'], 80)
        self.assertEqual(usage['cache_creation_input_tokens'], 10)
        self.assertEqual(usage['model_calls'], 2)
        self.assertEqual(usage['tool_calls'], 1)
        self.assertEqual(usage['first_token_ms'], 250)
        self.assertEqual(usage['duration_ms'], 1000)
        self.assertNotIn('synthetic', json.dumps(usage))

    def test_missing_result_is_unknown_not_zero(self):
        usage = RuntimeUsage('').snapshot()
        self.assertIsNone(usage['input_tokens'])
        self.assertIsNone(usage['model_calls'])
        self.assertIsNone(usage['first_token_ms'])
        self.assertEqual(usage['status'], 'failed')

    def test_official_tokenizer_known_chinese_and_english_ids_offline(self):
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            counter = TokenCounter('deepseek-v4-pro[1m]')
            tokenizer, manifest = load_tokenizer()
            self.assertEqual(tokenizer.encode('你好，世界！', add_special_tokens=False).ids,
                             [30594, 303, 3427, 1175])
            self.assertEqual(tokenizer.encode('Hello, world!', add_special_tokens=False).ids,
                             [19923, 14, 2058, 3])
            self.assertEqual(counter.count('你好，世界！'), 4)
            self.assertEqual(counter.count('Hello, world!'), 4)
            self.assertEqual(counter.count(''), 0)
            self.assertEqual(counter.metadata['revision'], manifest['revision'])
            self.assertEqual(counter.metadata['sha256'], manifest['sha256'])
            self.assertEqual(counter.metadata['status'], 'ready')

    def test_component_counts_use_tokenizer_and_do_not_retain_text(self):
        tracker = RuntimeUsage('你好，世界！', model='deepseek-v4-flash')
        tracker.set_component('user_message', 'Hello, world!')
        tracker.set_component('history', 'Hello, world!')
        tracker.add_component('tool_description', '{"name":"synthetic"}')
        tracker.capture(UserMessage(content=[ToolResultBlock(tool_use_id='fake', content='你好，世界！')]))
        estimate = tracker.snapshot()['context_estimate']
        self.assertEqual(estimate['method'], 'local_tokenizer')
        for key in ('system_prompt_tokens', 'user_message_tokens', 'history_tokens', 'tool_result_tokens'):
            self.assertEqual(estimate[key], 4)
        self.assertGreater(estimate['tool_description_tokens'], 0)
        self.assertNotIn('你好', json.dumps(estimate, ensure_ascii=False))
        self.assertNotIn('synthetic', json.dumps(estimate))

    def test_unsupported_model_and_missing_resources_never_use_character_fallback(self):
        for model in ('claude-sonnet', 'deepseek-v4-flash-vision-exp', 'deepseek-chat'):
            tracker = RuntimeUsage('你好，世界！', model=model)
            estimate = tracker.snapshot()['context_estimate']
            self.assertEqual(estimate['tokenizer']['status'], 'model_not_supported')
            self.assertIsNone(estimate['system_prompt_tokens'])
        with patch('app.services.token_counter.load_tokenizer', side_effect=OSError('missing')):
            tracker = RuntimeUsage('Hello, world!', model='deepseek-v4-pro')
            estimate = tracker.snapshot()['context_estimate']
            self.assertEqual(estimate['tokenizer']['status'], 'unavailable')
            self.assertIsNone(estimate['system_prompt_tokens'])

    def test_report_filters_and_preserves_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / 'synthetic.db')
            database.initialize()
            store = ConversationStore(database)
            first, second = store.create('fake'), store.create('other')
            usage = RuntimeUsage('你好，世界！', model='deepseek-v4-pro').snapshot()
            usage.update(input_tokens=100, output_tokens=20, first_token_ms=10)
            telemetry = UsageStore(database)
            telemetry.add(first, 'fake', usage)
            telemetry.add(first, 'fake', usage)
            telemetry.add(second, 'other', usage)
            before = database.path.read_bytes()
            report = report_module.report(database.path, 'conversation', first)
            self.assertEqual(list(report), [first])
            self.assertEqual(report[first]['turns'], 2)
            self.assertEqual(report[first]['context_estimates'][0]['system_prompt_tokens'], 4)
            self.assertEqual(report[first]['context_estimates'][0]['tokenizer']['status'], 'ready')
            self.assertEqual(report[first]['totals']['input_tokens'], 200)
            self.assertEqual(report[first]['average_first_token_ms'], 10)
            self.assertIsNone(report[first]['totals']['model_calls'])
            self.assertEqual(report_module.report(database.path, 'agent', 'fake')['fake']['turns'], 2)
            self.assertEqual(database.path.read_bytes(), before)
            with self.assertRaises(sqlite3.OperationalError):
                report_module.report(Path(directory) / 'missing.db')
            self.assertFalse((Path(directory) / 'missing.db').exists())

"""Deterministic telemetry and read-only reporting, using synthetic data only."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.services.token_counter import TokenCounter, load_tokenizer
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.usage_store import UsageStore

spec = importlib.util.spec_from_file_location('usage_report', Path(__file__).resolve().parents[1] / 'scripts/usage_report.py')
report_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_module)


class UsageTests(unittest.TestCase):
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

    def test_unsupported_model_and_missing_resources_never_use_character_fallback(self):
        for model in ('claude-sonnet', 'deepseek-v4-flash-vision-exp', 'deepseek-chat'):
            counter = TokenCounter(model)
            self.assertEqual(counter.metadata['status'], 'model_not_supported')
            self.assertIsNone(counter.count('你好，世界！'))
        with patch('app.services.token_counter.load_tokenizer', side_effect=OSError('missing')):
            counter = TokenCounter('deepseek-v4-pro')
            self.assertEqual(counter.metadata['status'], 'unavailable')
            self.assertIsNone(counter.count('Hello, world!'))

    def test_report_filters_and_preserves_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / 'synthetic.db')
            database.initialize()
            store = ConversationStore(database)
            first, second = store.create('fake'), store.create('other')
            counter = TokenCounter('deepseek-v4-pro')
            usage = {'runtime': 'deep_agents', 'input_tokens': 100, 'output_tokens': 20, 'model_calls': None, 'first_token_ms': 10,
                     'context_estimate': {'method': 'local_tokenizer', 'tokenizer': dict(counter.metadata),
                                          'system_prompt_tokens': counter.count('你好，世界！')}}
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

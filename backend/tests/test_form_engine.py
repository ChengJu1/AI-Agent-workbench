import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.platform.form_engine import EXTRACT, FormEngine, McpDriver


class ReadOnlyFormTests(unittest.TestCase):
    def test_extraction_script_never_writes_to_the_page(self):
        writes = r'\.(click|focus|submit|dispatchEvent|setAttribute|removeAttribute|appendChild|remove)\(|\.value\s*=[^=]|\.dataset\.\w+\s*=|innerHTML\s*='
        self.assertIsNone(re.search(writes, EXTRACT))

    def test_mcp_driver_only_evaluates(self):
        client = type('C', (), {})()
        client.call = AsyncMock(return_value='[]')
        fields = asyncio.run(FormEngine(McpDriver(client, lambda raw: [{'key': 'f0'}])).extract())
        self.assertEqual(fields, [{'key': 'f0'}])
        [(name, arguments)] = [c.args for c in client.call.call_args_list]
        self.assertEqual(name, 'browser_evaluate')
        self.assertTrue(arguments['function'].startswith('() => {'))


if __name__ == '__main__':
    unittest.main()

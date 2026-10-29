"""What the model API receives for tool results; built offline, no request is sent."""
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.config import Settings
from app.runtime.deep_agents import chat_model
from app.services.token_counter import TokenCounter


class ToolResultPayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = dataclasses.replace(Settings(database_path=Path(temporary.name) / 'synthetic.db'), deepagents_api_key='offline-only')
        self.model = chat_model(settings)

    def sent(self, content):
        call = {'name': 'mcp__workbench_team__delegate', 'args': {}, 'id': 'call-1'}
        payload = self.model._get_request_payload([HumanMessage('合成问题'), AIMessage('', tool_calls=[call]),
                                                   ToolMessage(content, tool_call_id='call-1')])
        return payload['messages'][-1]['content']

    def test_chinese_text_results_are_sent_as_plain_text_not_escaped_json(self):
        result = json.dumps({'reply': '安全评审认为批量通过必须逐单校验权限。' * 50}, ensure_ascii=False)
        sent = self.sent([{'type': 'text', 'text': result}])
        self.assertEqual(sent, result)
        self.assertNotIn('\\u', sent)
        counter = TokenCounter('deepseek-v4-flash')
        escaped = json.dumps([{'type': 'text', 'text': result}])
        # 修复前的发送方式大约是 6 倍 token。
        self.assertGreater(counter.count(escaped), 5 * counter.count(sent))

    def test_several_text_blocks_are_joined_and_other_content_is_left_alone(self):
        self.assertEqual(self.sent([{'type': 'text', 'text': '第一段'}, {'type': 'text', 'text': '第二段'}]), '第一段第二段')
        self.assertEqual(self.sent('已经是文本'), '已经是文本')
        mixed = [{'type': 'text', 'text': '截图'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]
        self.assertIsInstance(self.sent(mixed), str)


if __name__ == '__main__':
    unittest.main()

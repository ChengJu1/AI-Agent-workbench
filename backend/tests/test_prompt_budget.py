"""Per-call prompt cost: only enabled capability guidance, short file tools, and a cache-stable prefix."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import Field

from app.config import Settings
from app.container import build_services
from app.models.api import CreateAgentRequest
from app.runtime.deep_agents import FILE_TOOL_DESCRIPTIONS
from app.runtime.prompts import build_system_prompt


class Capture(FakeListChatModel):
    requests: list = Field(default_factory=list)
    tools: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.tools = [convert_to_openai_tool(tool) for tool in tools]
        return self

    async def _astream(self, messages, **kwargs):
        self.requests.append(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content='合成回答', chunk_position='last'))


class PromptBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))

    def agent(self, capabilities):
        return self.services.registry.create(CreateAgentRequest(
            name='合成助手', description='测试', system_prompt='合成助手。', platform_capabilities=capabilities))

    def test_guidance_only_for_enabled_capabilities(self):
        files = build_system_prompt(self.agent(['files']), None, 1000)
        self.assertIn('list_files', files)
        self.assertNotIn('浏览器填表', files)
        self.assertNotIn('网页先搜索', files)
        self.assertIn('不可信资料', files)
        web = build_system_prompt(self.agent(['web']), None, 1000)
        self.assertIn('网页先搜索', web)
        self.assertNotIn('list_files', web)

    def test_turn_state_stays_out_of_the_system_prompt_and_the_saved_history(self):
        agent = self.agent(['files'])
        cid = self.services.conversations.create(agent.id)
        model = Capture(responses=['unused'])
        self.services.deep_agents.model_factory = lambda: model

        async def send(text):
            prepared = self.services.conversations.prepare(cid, text)
            return [event async for event in self.services.conversations.stream(cid, text, prepared)]

        asyncio.run(send('第一轮'))
        asyncio.run(send('必须用中文回答。第二轮'))
        first, second = model.requests
        self.assertEqual(first[0].content, second[0].content)  # Same prefix on every turn: the cache can hit.
        self.assertNotIn('本轮结构化任务状态', second[0].content)
        self.assertTrue(second[-2].content.startswith('【平台状态'))
        self.assertIn('必须用中文回答', second[-2].content)  # Requirements still reach the model each turn.
        self.assertEqual(second[-1].content, '必须用中文回答。第二轮')
        self.assertEqual([m.content for m in second[1:3]], ['第一轮', '合成回答'])  # Earlier turns carry no stale state.
        self.assertEqual({tool['function']['name']: tool['function']['description'] for tool in model.tools
                          if tool['function']['name'] in FILE_TOOL_DESCRIPTIONS}, FILE_TOOL_DESCRIPTIONS)
        with SqliteSaver.from_conn_string(str(self.services.deep_agents.settings.checkpoint_path)) as saver:
            graph = self.services.deep_agents._graph(model, self.services.deep_agents.conversation_directory(cid), 'x', saver)
            saved = graph.get_state({'configurable': {'thread_id': cid}}).values['messages']
        self.assertFalse(any('平台状态' in str(message.content) for message in saved))
        self.assertEqual(len(saved), 4)

    def test_reasoning_effort_is_validated_and_passed_to_the_model(self):
        with self.assertRaises(ValueError):
            Settings(deepagents_reasoning_effort='off')
        runtime = build_services(Settings(database_path=self.services.deep_agents.settings.database_path,
                                          deepagents_reasoning_effort='none', deepagents_api_key='synthetic')).deep_agents
        self.assertEqual(runtime._model().extra_body, {'reasoning_effort': 'none'})
        self.assertIsNone(self.services.deep_agents.settings.deepagents_reasoning_effort)


if __name__ == '__main__':
    unittest.main()

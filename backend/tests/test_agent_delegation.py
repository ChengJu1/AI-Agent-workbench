"""The delegate tool with a scripted model: no real model calls, synthetic data only."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from app.config import Settings
from app.container import build_services
from app.tools.team_tools import DELEGATION_LIMIT, TOOL_NAME


DRAFT = {'draft': {'records': [{'date': '2026-10-21', 'task': '合成任务', 'hours': 1}], 'total_hours': 1}}


def text_of(message):
    content = message.content
    return content if isinstance(content, str) else ''.join(part.get('text', '') for part in content if isinstance(part, dict))


class TeamModel(FakeListChatModel):
    """The lead (its prompt lists team members) delegates as scripted; members answer or call a scripted tool."""
    responses: list = Field(default_factory=lambda: ['unused'])
    lead_calls: list = Field(default_factory=list)
    member_call: dict | None = None
    bound: list = Field(default_factory=list)
    member_tasks: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound.append({tool.name for tool in tools})
        return self

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        lead = '## 团队成员' in text_of(messages[0])
        last_human = max(index for index, message in enumerate(messages) if message.type == 'human')
        results = [text_of(message) for message in messages[last_human:] if message.type == 'tool']
        if not results and (self.lead_calls if lead else self.member_call):
            calls = self.lead_calls if lead else [self.member_call]
            yield ChatGenerationChunk(message=AIMessageChunk(content='', chunk_position='last', tool_call_chunks=[
                {'name': name, 'args': json.dumps(arguments, ensure_ascii=False), 'id': f'call-{index}', 'index': index}
                for index, (name, arguments) in enumerate(calls)]))
            return
        if not lead:
            self.member_tasks.append(text_of([message for message in messages if message.type == 'human'][-1]))
        reply = '汇总：' + ' | '.join(results) if lead else '成员结果'
        yield ChatGenerationChunk(message=AIMessageChunk(content=reply, chunk_position='last',
            usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}))


class DelegationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))
        self.model = TeamModel()
        self.services.deep_agents.model_factory = lambda: self.model
        self.lead = self.create_agent('负责人')
        self.member = self.create_agent('研究员')
        self.services.teams.set_members(self.lead.id, [self.member.id])
        self.parent = self.services.conversations.create(self.lead.id)

    def create_agent(self, name):
        from app.models.api import CreateAgentRequest
        return self.services.registry.create(CreateAgentRequest(name=name, description=f'{name}简介', system_prompt='回答问题。',
                                                                platform_capabilities=['files']))

    def delegate(self, member_id=None, task='查一下合成资料'):
        return (TOOL_NAME, {'member_id': member_id or self.member.id, 'task': task})

    def send(self, content='合成请求', cid=None):
        cid = cid or self.parent
        async def run():
            prepared = self.services.conversations.prepare(cid, content)
            return [event async for event in self.services.conversations.stream(cid, content, prepared)]
        with patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real model forbidden')):
            return asyncio.run(run())

    def tool_result(self, events):
        reply = ''.join(event['content'] for event in events if event['type'] == 'delta')
        return [json.loads(part) if part.startswith('{') else part for part in reply.removeprefix('汇总：').split(' | ')]

    def test_lead_delegates_and_member_runs_in_a_reused_child_conversation(self):
        self.model.lead_calls = [self.delegate()]
        events = self.send()
        result = self.tool_result(events)[0]
        child = result['child_conversation_id']
        self.assertEqual((result['status'], result['reply'], result['member_name']), ('complete', '成员结果', '研究员'))
        self.assertEqual(result['usage']['model_calls'], 1)
        self.assertEqual(self.model.member_tasks, ['查一下合成资料'])

        kinds = [event['type'] for event in events]
        self.assertLess(kinds.index('delegation_started'), kinds.index('delegation_finished'))
        started = next(event for event in events if event['type'] == 'delegation_started')
        self.assertEqual((started['member_id'], started['child_conversation_id'], started['task']), (self.member.id, child, '查一下合成资料'))

        messages = self.services.store.get_messages(child)
        self.assertEqual([(item['role'], item['content']) for item in messages], [('user', '查一下合成资料'), ('assistant', '成员结果')])
        self.assertEqual(messages[0]['delegated_by'], self.lead.id)
        saved = self.services.store.get_messages(self.parent)[-1]['delegations']
        self.assertEqual([(item['member_id'], item['child_conversation_id'], item['status']) for item in saved], [(self.member.id, child, 'complete')])

        self.assertEqual(self.tool_result(self.send('再来一次'))[0]['child_conversation_id'], child)
        self.assertEqual(len(self.services.store.get_messages(child)), 4)
        self.assertEqual(len(self.services.teams.delegations(self.parent)), 1)

    def test_member_cannot_delegate_even_with_its_own_team(self):
        self.services.teams.set_members(self.member.id, [self.lead.id])
        self.model.lead_calls = [self.delegate()]
        self.send()
        lead_tools, member_tools = self.model.bound[0], self.model.bound[1]
        self.assertIn(TOOL_NAME, lead_tools)
        self.assertNotIn(TOOL_NAME, member_tools)
        # Without a team the tool is not registered at all.
        self.services.teams.set_members(self.lead.id, [])
        self.model.lead_calls, self.model.bound = [], []
        self.send('没有团队')
        self.assertNotIn(TOOL_NAME, self.model.bound[0])

    def test_unknown_member_busy_member_and_the_per_turn_limit_are_refused(self):
        other = self.create_agent('写手')
        self.services.teams.set_members(self.lead.id, [self.member.id, other.id])
        self.model.lead_calls = [self.delegate(), self.delegate()]
        results = self.tool_result(self.send())
        self.assertEqual(sorted(result['status'] if isinstance(result, dict) else 'busy' for result in results), ['busy', 'complete'])
        self.assertTrue(any('正在处理上一项任务' in result for result in results if isinstance(result, str)))

        self.model.lead_calls = [self.delegate('timesheet_assistant')]
        self.assertIn('is not one of', ' '.join(map(str, self.tool_result(self.send('派给外人')))))

        self.model.lead_calls = [self.delegate(other.id if index % 2 else self.member.id, f'任务{index}') for index in range(DELEGATION_LIMIT + 1)]
        results = self.tool_result(self.send('派很多次'))
        self.assertEqual(len(results), DELEGATION_LIMIT + 1)
        self.assertEqual(sum('达到上限' in result for result in results if isinstance(result, str)), 1)

    def test_member_approvals_stay_in_the_child_conversation(self):
        self.services.teams.set_members(self.lead.id, ['timesheet_assistant'])
        self.model.lead_calls = [self.delegate('timesheet_assistant', '提交合成工时')]
        self.model.member_call = ('mcp__timesheet_cli__submit_timesheet', DRAFT)
        events = self.send()
        result = self.tool_result(events)[0]
        self.assertEqual((result['status'], result['pending_approvals']), ('needs_approval', 1))
        child = result['child_conversation_id']
        self.assertEqual([action['conversation_id'] for action in self.services.tool_store.get_pending_actions(child)], [child])
        self.assertEqual(self.services.tool_store.get_pending_actions(self.parent), [])
        self.assertFalse(any(event['type'] == 'approval_required' for event in events))


if __name__ == '__main__':
    unittest.main()

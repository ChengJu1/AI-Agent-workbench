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
from app.tools.team_tools import DELEGATE_REPLY_CHARS, SPEECH_REPLY_CHARS, DELEGATION_LIMIT, DISCUSS_TOOL, END_MARK, PROPOSE_TOOL, TOOL_NAME


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
    member_reply: str = '成员结果'

    def bind_tools(self, tools, **kwargs):
        self.bound.append({tool.name for tool in tools})
        return self

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        lead = '## 协作' in text_of(messages[0])
        last_human = max(index for index, message in enumerate(messages) if message.type == 'human')
        results = [text_of(message) for message in messages[last_human:] if message.type == 'tool']
        if not results and (self.lead_calls if lead else self.member_call):
            calls = self.lead_calls if lead else [self.member_call]
            yield ChatGenerationChunk(message=AIMessageChunk(content='', chunk_position='last', tool_call_chunks=[
                {'name': name, 'args': json.dumps(arguments, ensure_ascii=False), 'id': f'call-{index}', 'index': index}
                for index, (name, arguments) in enumerate(calls)]))
            return
        if not lead:
            task = text_of([message for message in messages if message.type == 'human'][-1])
            self.member_tasks.append(task)
        # 群聊里听到别人发言后就表示结束；首次发言给出意见。
        reply = '汇总：' + ' | '.join(results) if lead else END_MARK if '其他成员的发言' in task else self.member_reply
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
        self.parent = self.services.conversations.create(self.lead.id)

    def create_agent(self, name):
        from app.models.api import CreateAgentRequest
        return self.services.registry.create(CreateAgentRequest(name=name, description=f'{name}简介', system_prompt='回答问题。',
                                                                platform_capabilities=['files']))

    def approve(self, participants):
        """A team plan the user approved; returns the participant ids handed to the lead."""
        plan = self.services.teams.validate_plan(self.lead, {'summary': '合成计划', 'participants': participants})
        action = self.services.tool_store.create_pending_action(self.parent, self.lead.id, 'workbench_team', 'team_plan', plan)
        self.services.approvals.decide(action, True)
        return self.services.teams.approved_participants(self.parent)

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
        # 平台在任务后面附上篇幅要求，避免成员写超截断上限。
        self.assertEqual(len(self.model.member_tasks), 1)
        self.assertTrue(self.model.member_tasks[0].startswith('查一下合成资料\n\n（平台说明'))
        self.assertIn(f'{DELEGATE_REPLY_CHARS} 字以内', self.model.member_tasks[0])

        kinds = [event['type'] for event in events]
        self.assertLess(kinds.index('delegation_started'), kinds.index('delegation_finished'))
        started = next(event for event in events if event['type'] == 'delegation_started')
        self.assertEqual((started['member_id'], started['child_conversation_id'], started['task']), (self.member.id, child, '查一下合成资料'))

        messages = self.services.store.get_messages(child)
        self.assertEqual([item['role'] for item in messages], ['user', 'assistant'])
        self.assertTrue(messages[0]['content'].startswith('查一下合成资料\n\n（平台说明'))
        self.assertEqual(messages[0]['delegated_by'], self.lead.id)
        saved = self.services.store.get_messages(self.parent)[-1]['delegations']
        self.assertEqual([(item['member_id'], item['child_conversation_id'], item['status']) for item in saved], [(self.member.id, child, 'complete')])

        self.assertEqual(self.tool_result(self.send('再来一次'))[0]['child_conversation_id'], child)
        self.assertEqual(len(self.services.store.get_messages(child)), 4)
        self.assertEqual(len(self.services.teams.delegations(self.parent)), 1)

    def test_members_never_get_collaboration_tools(self):
        self.model.lead_calls = [self.delegate()]
        self.send()
        lead_tools, member_tools = self.model.bound[0], self.model.bound[1]
        self.assertLessEqual({TOOL_NAME, PROPOSE_TOOL}, lead_tools)
        self.assertNotIn(DISCUSS_TOOL, lead_tools)  # 没有批准的计划时不能讨论。
        self.assertFalse(any(name.startswith('mcp__workbench_team__') for name in member_tools))

    def test_more_than_one_unplanned_delegation_needs_an_approved_plan(self):
        other = self.create_agent('写手')
        self.model.lead_calls = [self.delegate(), self.delegate(other.id)]
        results = self.tool_result(self.send())
        self.assertEqual(sum(isinstance(result, dict) and result['status'] == 'complete' for result in results), 1)
        self.assertTrue(any(PROPOSE_TOOL in result for result in results if isinstance(result, str)))
        self.model.lead_calls = [self.delegate(self.lead.id)]
        self.assertIn('is not one of', ' '.join(map(str, self.tool_result(self.send('派给自己')))))

    def test_proposing_a_plan_waits_for_the_user_and_blocks_delegation_until_then(self):
        plan = {'summary': '合成计划', 'participants': [{'name': '评审', 'instructions': '挑问题。', 'capabilities': ['files']}]}
        self.model.lead_calls = [(PROPOSE_TOOL, plan), self.delegate()]
        events = self.send()
        results = self.tool_result(events)
        self.assertEqual(results[0]['status'], 'waiting_for_user')
        self.assertIn('等待用户确认', results[1])
        waiting = [event['action'] for event in events if event['type'] == 'approval_required']
        self.assertEqual([(action['tool_name'], action['params']['participants'][0]['name']) for action in waiting], [('workbench_team', '评审')])
        self.model.lead_calls = [(PROPOSE_TOOL, {'summary': '越权', 'participants': [{'name': 'x', 'instructions': 'y', 'capabilities': ['web']}]})]
        self.assertIn('is not one of', ' '.join(map(str, self.tool_result(self.send('越权计划')))))

    def test_approved_temporary_agents_run_and_busy_members_and_the_limit_are_refused(self):
        writer, reviewer = self.approve([{'agent_id': self.member.id}, {'name': '评审', 'instructions': '挑问题。', 'capabilities': []}])
        self.model.lead_calls = [self.delegate(reviewer), self.delegate(reviewer)]
        results = self.tool_result(self.send())
        self.assertEqual(sorted(result['status'] if isinstance(result, dict) else 'busy' for result in results), ['busy', 'complete'])
        self.assertTrue(any('正在处理上一项任务' in result for result in results if isinstance(result, str)))
        self.assertEqual(next(result for result in results if isinstance(result, dict))['member_name'], '评审')
        self.assertTrue(self.services.teams.delegations(self.parent)[0]['temporary'])

        self.model.lead_calls = [self.delegate(reviewer if index % 2 else writer, f'任务{index}') for index in range(DELEGATION_LIMIT + 1)]
        results = self.tool_result(self.send('派很多次'))
        self.assertEqual(len(results), DELEGATION_LIMIT + 1)
        self.assertEqual(sum('达到上限' in result for result in results if isinstance(result, str)), 1)

    def test_member_approvals_stay_in_the_child_conversation(self):
        self.model.lead_calls = [self.delegate('timesheet_assistant', '提交合成工时')]
        self.model.member_call = ('mcp__timesheet_cli__submit_timesheet', DRAFT)
        events = self.send()
        result = self.tool_result(events)[0]
        self.assertEqual((result['status'], result['pending_approvals']), ('needs_approval', 1))
        child = result['child_conversation_id']
        self.assertEqual([action['conversation_id'] for action in self.services.tool_store.get_pending_actions(child)], [child])
        self.assertEqual(self.services.tool_store.get_pending_actions(self.parent), [])
        self.assertFalse(any(event['type'] == 'approval_required' for event in events))

    def test_group_chat_members_take_turns_and_hear_each_other_verbatim(self):
        other = self.create_agent('评审')
        self.model.lead_calls = [(DISCUSS_TOOL, {'member_ids': self.approve([{'agent_id': self.member.id}, {'agent_id': other.id}]),
                                                 'topic': '合成方案怎么改'})]
        events = self.send()
        # 负责人同时拿到委派和讨论两种工具，按任务自己选。
        self.assertLessEqual({TOOL_NAME, DISCUSS_TOOL, PROPOSE_TOOL}, self.model.bound[0])
        result = self.tool_result(events)[0]
        # 第 1 轮：研究员先说，评审听到后表示结束；第 2 轮两人都表示结束，提前停止。
        self.assertEqual([(item['member_name'], item['round'], item['text']) for item in result['transcript']],
                         [('研究员', 1, '成员结果'), ('评审', 1, END_MARK), ('研究员', 2, END_MARK), ('评审', 2, END_MARK)])
        self.assertEqual((result['rounds_completed'], result['speaker_turns']), (2, 4))
        first, heard, research_again = self.model.member_tasks[0], self.model.member_tasks[1], self.model.member_tasks[2]
        self.assertIn('讨论题目：合成方案怎么改', first)
        self.assertIn(f'{SPEECH_REPLY_CHARS} 字以内', first)
        self.assertIn('【研究员·第1轮】成员结果', heard)
        # 第二次发言只带上次之后别人的新发言，不重复题目和自己的话。
        self.assertNotIn('讨论题目', research_again)
        self.assertIn('【评审·第1轮】', research_again)
        self.assertNotIn('【研究员·第1轮】', research_again)
        rounds = [event.get('round') for event in events if event['type'] == 'delegation_finished']
        self.assertEqual(rounds, [1, 1, 2, 2])
        self.assertEqual(len(self.services.teams.delegations(self.parent)), 2)
        self.assertEqual(len(self.services.store.get_messages(self.parent)[-1]['delegations']), 4)

    def test_speeches_written_longer_than_requested_reach_the_lead_whole(self):
        # 实测模型会写到要求篇幅的 1.5–1.8 倍；这样的发言不能被截断。
        other = self.create_agent('评审')
        members = self.approve([{'agent_id': self.member.id}, {'agent_id': other.id}])
        self.model.member_reply = '长' * (SPEECH_REPLY_CHARS * 2)
        self.model.lead_calls = [(DISCUSS_TOOL, {'member_ids': members, 'topic': '写长一点', 'rounds': 1})]
        transcript = self.tool_result(self.send())[0]['transcript']
        self.assertEqual(transcript[0]['text'], self.model.member_reply)
        # 下一位成员听到的也是完整原文。
        self.assertIn(f'【研究员·第1轮】{self.model.member_reply}\n', self.model.member_tasks[1] + '\n')

    def test_group_chat_stops_at_the_round_limit(self):
        other = self.create_agent('评审')
        members = self.approve([{'agent_id': self.member.id}, {'agent_id': other.id}])
        self.model.lead_calls = [(DISCUSS_TOOL, {'member_ids': members, 'topic': '只讨论一轮', 'rounds': 1})]
        result = self.tool_result(self.send())[0]
        self.assertEqual((result['rounds_completed'], result['speaker_turns']), (1, 2))
        self.model.lead_calls = [(DISCUSS_TOOL, {'member_ids': members, 'topic': '太多轮', 'rounds': 9})]
        self.assertIn('greater than the maximum of 3', ' '.join(map(str, self.tool_result(self.send('太多轮')))))


if __name__ == '__main__':
    unittest.main()

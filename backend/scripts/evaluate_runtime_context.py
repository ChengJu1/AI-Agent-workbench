"""Offline A/B/C mechanics comparison. Never reads .env or calls real models/sites.

Run: LANGSMITH_TRACING=false .venv/bin/python scripts/evaluate_runtime_context.py --output /tmp/context-comparison.json
This is NOT a model-quality or provider-billing benchmark.
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / 'tests'))

from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, ToolResultBlock, ToolUseBlock, UserMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import Field

from app.config import Settings
from app.container import build_services
from app.models.api import CreateAgentRequest
from app.models.applications import ApplicationSave
from app.models.profiles import ProfileSave
from app.services.token_counter import TokenCounter
from synthetic_application_site import FORM


class ScriptedContextModel(FakeListChatModel):
    action: str | None = None
    arguments: dict = Field(default_factory=dict)
    requests: list = Field(default_factory=list)
    tool_names: list = Field(default_factory=list)
    next_call: int = 0

    def bind_tools(self, tools, **kwargs):
        self.tool_names = [tool.name for tool in tools]
        return self

    async def _astream(self, messages, **kwargs):
        self.requests.append(messages)
        name, args = None, {}
        if self.action and self.next_call == 0:
            name, args = self.action, self.arguments
        elif self.action and self.next_call == 1:
            tool = next((m for m in reversed(messages) if m.type == 'tool'), None)
            if tool:
                content = tool.content if isinstance(tool.content, str) else tool.content[0].get('text', '')
                try:
                    reference = json.loads(content)
                except (TypeError, ValueError):
                    reference = {}
                if reference.get('offloaded'):
                    name, args = 'read_file', {'file_path': reference['path'], 'offset': 0, 'limit': 8}
        self.next_call += 1
        if name:
            yield ChatGenerationChunk(message=AIMessageChunk(content='', chunk_position='last', tool_call_chunks=[{
                'name': name, 'args': json.dumps(args), 'id': f'synthetic-{self.next_call}', 'index': 0}]))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content='合成核对完成，未提交。', chunk_position='last'))


def load_cases():
    return json.loads((BACKEND / 'evaluation/runtime-context-cases.json').read_text())


def run_case(group, case, root):
    settings = Settings(database_path=Path(root) / group / case['id'] / 'synthetic.db',
        deepagents_enabled=True, claude_result_offload_enabled=group == 'B',
        deepagents_summary_trigger_tokens=3000, deepagents_summary_trigger_messages=6,
        deepagents_summary_keep_messages=2)
    services = build_services(settings)
    base = services.knowledge.store.create_base('合成资料', '')
    services.knowledge.ingest(base['id'], 'synthetic.md', '合成岗位申请需要审批，不能自动提交。'.encode())
    profile = services.profiles.save(ProfileSave(name='合成档案', data={'basics': {'name': '合成候选人'}}))
    application = services.applications.save(ApplicationSave(company='合成公司', position='合成岗位'))
    agent = services.registry.create(CreateAgentRequest(name='合成对照助手', description='仅离线验收',
        system_prompt='核对合成资料，保留用户硬性要求，不得提交。',
        platform_capabilities=['web', 'applications'], knowledge_base_ids=[base['id']]))
    cid = services.conversations.create(agent.id, 'deep_agents' if group == 'C' else 'claude_sdk')
    arguments = {
        'web_read': {'url': 'http://synthetic.invalid/long-page'},
        'search_knowledge': {'knowledge_base_id': base['id'], 'query': '申请'},
        'application_prepare_kit': {'application_id': application['id'], 'profile_id': profile['id'],
            'profile_version': 1, 'items': [{'label': '姓名', 'source': {'kind': 'profile', 'ref': 'basics.name', 'version': 1}}]},
    }.get(case['tool'], {})
    action = ('mcp__workbench_knowledge__' if case['tool'] == 'search_knowledge' else 'mcp__workbench_platform__') + case['tool'] if case['tool'] else None
    models, usages, sdk_request_tokens, failures = [], [], [], 0
    evidence_matched = False
    counter = TokenCounter('deepseek-v4-pro')
    services.deep_agents.summary_model_factory = lambda: FakeListChatModel(responses=[
        '用户目标：核对合成申请。硬性要求：不得提交、只考虑上海。资料版本与台账ID以本轮结构化状态为准。待办：继续核对。'])

    async def query(prompt, options):
        # Display-only telemetry must never inflate the conversation text proxy.
        history = [{'role': message['role'], 'content': message['content']}
                   for message in services.store.get_messages(cid)]
        sdk_request_tokens.append(counter.count(options.system_prompt + json.dumps(history, ensure_ascii=False)))
        calls = 0
        if action:
            server, tool_name = action[len('mcp__'):].split('__', 1)
            async with create_connected_server_and_client_session(options.mcp_servers[server]['instance']) as session:
                yield AssistantMessage(content=[ToolUseBlock(id='synthetic', name=action, input=arguments)], model='fake')
                result = await session.call_tool(tool_name, arguments)
            calls += 1
            content = [item.model_dump(exclude_none=True) for item in result.content]
            yield UserMessage(content=[ToolResultBlock(tool_use_id='synthetic', content=content, is_error=result.isError)])
            sdk_request_tokens.append(counter.count(options.system_prompt + json.dumps(history + [content], ensure_ascii=False)))
            reference = json.loads(result.content[0].text)
            if reference.get('offloaded'):
                args = {'file_path': reference['path'], 'offset': 0, 'limit': 8}
                async with create_connected_server_and_client_session(options.mcp_servers['workbench_artifacts']['instance']) as session:
                    yield AssistantMessage(content=[ToolUseBlock(id='readback', name='mcp__workbench_artifacts__read_file', input=args)], model='fake')
                    read = await session.call_tool('read_file', args)
                calls += 1
                yield UserMessage(content=[ToolResultBlock(tool_use_id='readback', content=[item.model_dump(exclude_none=True) for item in read.content], is_error=read.isError)])
                sdk_request_tokens.append(counter.count(options.system_prompt + json.dumps(history + [content, [item.model_dump(exclude_none=True) for item in read.content]], ensure_ascii=False)))
        yield StreamEvent(uuid='synthetic', session_id=cid, event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '合成核对完成，未提交。'}})
        yield ResultMessage(subtype='success', duration_ms=0, duration_api_ms=0, num_turns=calls + 1, session_id=cid, is_error=False)

    async def collect(text):
        prepared = services.conversations.prepare(cid, text)
        return [event async for event in services.conversations.stream(cid, text, prepared)]

    # Source is the repository's synthetic form; read() is stubbed, never HTTP.
    page = {'url': 'http://synthetic.invalid/long-page', 'text': FORM + '\n合成长页面段落。' * 5000 + '\nEND_OF_SYNTHETIC_PAGE'}
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'synthetic', 'ANTHROPIC_MODEL': 'deepseek-v4-pro'}), \
         patch('app.services.claude_runtime.query', query), \
         patch('langchain_deepseek.ChatDeepSeek', side_effect=AssertionError('Real models are forbidden')), \
         patch.object(services.platform.web, 'read', return_value=page):
        for index in range(case['turns']):
            model = ScriptedContextModel(responses=['unused'], action=action, arguments=arguments)
            models.append(model)
            services.deep_agents.model_factory = lambda: model
            text = '核对合成申请。硬性要求：不得提交、只考虑上海。' if index == 0 else f'第 {index + 1} 轮继续核对。' + '合成过程记录。' * 500
            events = asyncio.run(collect(text))
            failures += int(events[-1]['type'] != 'done' or any(e['type'] == 'tool_finished' and not e['success'] for e in events))
            evidence_matched |= any(e['type'] == 'knowledge' and e['evidence']['status'] == 'matched' for e in events)
            usages.extend(e['usage'] for e in events if e['type'] == 'usage')
    requests = [counter.count(json.dumps([{'role': m.type, 'content': m.content,
        'tool_calls': getattr(m, 'tool_calls', [])} for m in request], ensure_ascii=False))
        for model in models for request in model.requests] if group == 'C' else sdk_request_tokens
    management = [usage['context_management'] for usage in usages]
    checks = {'no_approval_executed': not any(action['status'] in ('approved', 'executing') for action in services.tool_store.get_pending_actions(cid)),
              'original_transcript_preserved': len(services.store.get_messages(cid)) == case['turns'] * 2}
    if case['id'] == 'knowledge_qa':
        checks['evidence_matched'] = evidence_matched
    if case['id'] == 'application_kit':
        saved = services.applications.get(application['id'])
        checks['kit_uses_reviewed_profile'] = saved['kit']['items'][0]['value'] == '合成候选人'
        checks['application_not_submitted'] = saved['stage'] == 'preparing' and not saved['applied_at']
    if case['id'] == 'long_web':
        checks['expected_offload_policy'] = sum(item['offloaded_results'] for item in management) == (0 if group == 'A' else 1)
        checks['expected_readback'] = (sum(item['readback_result_chars'] for item in management) > 0) == (group != 'A')
    if case['id'] == 'long_conversation':
        checks['only_C_summarizes'] = (sum(item['summary_model_calls'] for item in management) > 0) == (group == 'C')
        if group == 'C':
            checks['goal_and_hard_requirement_survive'] = '不得提交' in str(models[-1].requests[-1]) and '只考虑上海' in str(models[-1].requests[-1])
    failures += sum(not passed for passed in checks.values())
    return {'group': group, 'case': case['id'], 'turns': case['turns'], 'failures': failures,
        'mechanics_checks': checks,
        'provider_input_tokens': None, 'provider_output_tokens': None, 'cache_hit_rate': None,
        'observed_request_text_token_proxy': sum(requests) if all(value is not None for value in requests) else None,
        'token_proxy_scope': 'C: graph message JSON; A/B: system prompt + local transcript + observed results; excludes wire/chat templates and schemas; NOT billing or a fair framework ranking',
        'tool_calls': sum(usage.get('tool_calls', 0) for usage in usages),
        'offloaded_results': sum(item['offloaded_results'] for item in management),
        'original_result_chars': sum(item['original_result_chars'] for item in management),
        'forwarded_result_chars': sum(item['forwarded_result_chars'] for item in management),
        'readback_result_chars': sum(item['readback_result_chars'] for item in management),
        'summary_model_calls': sum(item['summary_model_calls'] for item in management),
        'summaries_completed': sum(item.get('summaries_completed', 0) for item in management),
        'summary_history_token_windows': [{'before': item.get('history_tokens_before_summary'),
            'after': item.get('history_tokens_after_summary')} for item in management if item.get('summaries_completed')],
        'first_token_ms': [usage['first_token_ms'] for usage in usages],
        'duration_ms': [usage['duration_ms'] for usage in usages],
        'quality_score': None, 'quality_note': 'Scripted replies validate mechanics only; real quality scoring requires authorized model runs.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as root:
        rows = [run_case(group, case, root) for group in ('A', 'B', 'C') for case in load_cases()]
    args.output.write_text(json.dumps({'mode': 'synthetic_models_only', 'real_model_calls': 0, 'results': rows}, ensure_ascii=False, indent=2))
    print(f'Saved {len(rows)} synthetic comparisons to {args.output}')
    if any(row['failures'] for row in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

"""Opt-in Deep Agents conversation runtime, with SQLite state and read-only tools."""
from contextlib import aclosing
import logging
from pathlib import Path
import shutil
from time import perf_counter
from uuid import UUID

import anyio

from app.config import DEFAULT_SKILL_READ_BUDGET_CHARS
from app.errors import ServiceError
from app.runtime.prompts import build_system_prompt
from app.runtime.tool_activity import ToolActivity
from app.runtime.tools import RuntimeTools
from app.runtime.result_offload import ResultOffloader
from app.runtime.context_summary import WorkbenchSummarizationMiddleware
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.notes_evidence import notes_servers
from app.services.skill_loads import SkillLoads
from app.platform.service import SERVER_NAME as PLATFORM_SERVER
from app.services.token_counter import TokenCounter
from app.storage.usage_store import UsageStore


logger = logging.getLogger(__name__)


class DeepAgentsRuntime:
    skill_read_budget_chars = DEFAULT_SKILL_READ_BUDGET_CHARS

    def __init__(self, settings, audit_store, model_factory=None):
        self.settings, self.audit_store = settings, audit_store
        self.model_factory = model_factory or self._model
        self.skill_read_budget_chars = settings.skill_read_budget_chars
        self.tool_services = RuntimeTools(audit_store)
        self.summary_model_factory = None

    def _model(self):
        if not self.settings.deepagents_api_key:
            raise ServiceError('缺少独立的 WORKBENCH_DEEPAGENTS_API_KEY 配置。', 503)
        from langchain_deepseek import ChatDeepSeek
        return ChatDeepSeek(model=self.settings.deepagents_model, api_key=self.settings.deepagents_api_key,
                            api_base=self.settings.deepagents_base_url, streaming=True, max_retries=0)

    def conversation_directory(self, conversation_id):
        # Database-generated UUIDs are the only accepted thread/directory identifiers.
        identifier = str(UUID(conversation_id))
        return Path(self.settings.artifacts_directory) / identifier

    def _graph(self, model, directory, prompt, checkpointer, tools=(), summary=None):
        from deepagents import create_deep_agent
        from deepagents.middleware.filesystem import FilesystemMiddleware
        from deepagents.profiles import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
        from app.runtime.read_only_backend import SessionReadOnlyBackend

        # Pinned Deep Agents 0.7.19 profiles are needed: subagents=[] alone still
        # auto-creates its general-purpose agent. Match this exact model/provider.
        provider = model._get_ls_params().get('ls_provider')
        identifier = getattr(model, 'model_name', None) or getattr(model, 'model', None)
        if not provider:
            raise ServiceError('无法确定模型对应的受限运行配置。', 503)
        register_harness_profile(f'{provider}:{identifier}' if identifier else provider, HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            excluded_middleware=frozenset({'SummarizationMiddleware'}),
        ))
        backend = SessionReadOnlyBackend(directory)
        filesystem = FilesystemMiddleware(backend=backend, tools=['ls', 'read_file'],
            tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None)
        return create_deep_agent(model=model, tools=list(tools), system_prompt=prompt, backend=backend,
                                 middleware=[filesystem, summary or WorkbenchSummarizationMiddleware(model, self.settings, directory=directory)],
                                 subagents=[], checkpointer=checkpointer)

    async def stream(self, conversation_id, agent, user_message, context):
        if not self.settings.deepagents_enabled:
            raise ServiceError('Deep Agents 运行时尚未启用。', 409)
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langchain_core.messages import AIMessage, ToolMessage

        started, first_token, failure = perf_counter(), None, None
        calls, tool_calls, completed = 0, 0, False
        tokens = {key: [] for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')}
        model = self.model_factory()
        directory = self.conversation_directory(conversation_id)
        directory.mkdir(parents=True, exist_ok=True)
        checkpoint = Path(self.settings.checkpoint_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        platform = self.tool_services.platform
        native_browser = platform is not None and platform.browser.status().get('provider') == 'native_mcp'
        prompt = build_system_prompt(agent, context.business_context, self.skill_read_budget_chars, native_browser)
        prompt += '\n\n转存文件仅能用 ls 和 read_file 在当前会话目录中只读访问。业务工具使用 mcp__服务名__工具名；修改和提交必须遵守工具实际返回的确认要求，等待工作台确认清单。不得使用未注册的工具、子 Agent 或命令执行。'
        counter = TokenCounter(self.settings.deepagents_model)
        evidence = context.evidence or (KnowledgeEvidence() if agent.knowledge_base_ids or notes_servers(agent) else None)
        loads = context.skill_loads if context.skill_loads is not None else (SkillLoads(self.skill_read_budget_chars) if agent.bound_skills else None)
        turn = self.tool_services.prepare(conversation_id, agent, evidence, loads)
        activity = ToolActivity()
        offloader = ResultOffloader(self.settings.artifacts_directory, conversation_id, self.settings.tool_result_offload_chars)
        summary = WorkbenchSummarizationMiddleware(model, self.settings, context.business_context,
            self.summary_model_factory() if self.summary_model_factory else None, directory=directory)
        evidence_revision, last_skills = 0, []

        def observations():
            nonlocal evidence_revision, last_skills
            events = activity.drain()
            if loads is not None and loads.snapshot() != last_skills:
                last_skills = loads.snapshot()
                events.append({'type': 'skills', 'skills': last_skills, 'mode': 'on_demand'})
            if evidence is not None:
                revision, snapshot = evidence.snapshot()
                if revision != evidence_revision:
                    evidence_revision = revision
                    events.append({'type': 'knowledge', 'evidence': snapshot})
            return events

        try:
            with activity.bind(), offloader.bind():
                async with turn.langchain():
                    async with AsyncSqliteSaver.from_conn_string(str(checkpoint)) as saver:
                        graph = self._graph(model, directory, prompt, saver, turn.tools, summary)
                        config = {'configurable': {'thread_id': conversation_id}, 'recursion_limit': agent.max_turns * 2 + 2}
                        async with aclosing(graph.astream({'messages': [{'role': 'user', 'content': user_message}]},
                            config=config, stream_mode=['messages', 'updates'])) as events:
                            async for mode, data in events:
                                for event in observations():
                                    yield event
                                if mode == 'messages':
                                    message, metadata = data
                                    if metadata.get('langgraph_node') != 'model' or metadata.get('lc_source') == 'summarization':
                                        continue
                                    content = message.content
                                    text = content if isinstance(content, str) else ''.join(
                                        part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') == 'text')
                                    if text:
                                        if first_token is None:
                                            first_token = (perf_counter() - started) * 1000
                                        yield {'type': 'delta', 'content': text}
                                elif mode == 'updates':
                                    for node, update in data.items():
                                        if not isinstance(update, dict):
                                            continue
                                        for message in update.get('messages', []):
                                            if isinstance(message, AIMessage) and node == "model":
                                                calls += 1
                                                usage = message.usage_metadata or {}
                                                details = usage.get('input_token_details', {})
                                                for key, value in [('input_tokens', usage.get('input_tokens')), ('output_tokens', usage.get('output_tokens')),
                                                    ('cache_read_input_tokens', details.get('cache_read')), ('cache_creation_input_tokens', details.get('cache_creation'))]:
                                                    if isinstance(value, int) and not isinstance(value, bool):
                                                        tokens[key].append(value)
                                                for call in message.tool_calls:
                                                    tool_calls += 1
                                                    if call['name'] in turn.names:
                                                        continue
                                                    yield {'type': 'tool_started', 'tool_name': call['name'] if call['name'] in ('ls', 'read_file') else 'unavailable', 'call_id': call['id']}
                                            elif isinstance(message, ToolMessage) and message.name not in turn.names:
                                                yield {'type': 'tool_finished', 'tool_name': message.name if message.name in ('ls', 'read_file') else 'unavailable',
                                                       'call_id': message.tool_call_id, 'success': message.status != 'error'}
                        completed = True
        except Exception as error:
            message = 'MCP 工具服务暂时不可用，请稍后重试。' if turn.allowed_external else '模型未能完成本轮回复，请稍后重试。'
            failure = error if isinstance(error, ServiceError) else ServiceError(message, 502)
        finally:
            summary_calls = summary.metrics['summary_model_calls']
            # Totals include summary overhead only when both paths report usage.
            total_input = sum(tokens['input_tokens']) + summary.metrics['summary_input_tokens'] if tokens['input_tokens'] and len(tokens['input_tokens']) == calls and summary.summary_usage_complete else None
            total_output = sum(tokens['output_tokens']) + summary.metrics['summary_output_tokens'] if tokens['output_tokens'] and len(tokens['output_tokens']) == calls and summary.summary_usage_complete else None
            usage = {'runtime': 'deep_agents', **{key: sum(values) if values and len(values) == calls else None for key, values in tokens.items()},
                     'input_tokens': total_input, 'output_tokens': total_output,
                     'model_calls': (summary.metrics['main_model_calls'] + summary_calls) or None, 'tool_calls': tool_calls, 'first_token_ms': first_token,
                     'context_management': {'group': 'C', **offloader.metrics(), **summary.metrics,
                         'summary_usage_complete': summary.summary_usage_complete,
                         'summary_tokenizer': dict(summary.counter.metadata)},
                     'duration_ms': (perf_counter() - started) * 1000, 'status': 'complete' if completed else 'failed',
                     'context_estimate': {'method': 'local_tokenizer', 'tokenizer': dict(counter.metadata),
                         'system_prompt_tokens': counter.count(prompt), 'user_message_tokens': counter.count(user_message),
                         'history_tokens': None, 'tool_description_tokens': None, 'tool_result_tokens': None,
                         'limitation': 'SQLite graph history, middleware prompts and tool schemas are not measured in this stage.'}}
            if summary_calls:
                usage['cache_read_input_tokens'] = None
                usage['cache_creation_input_tokens'] = None
            if not completed:
                for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
                    usage[key] = None
            if not summary.summary_usage_complete:
                for name in ('summary_input_tokens', 'summary_output_tokens'):
                    usage['context_management'][name] = None
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(UsageStore(self.audit_store.database).add, conversation_id, agent.id, usage)
                except Exception:
                    logger.warning('保存 Deep Agents 用量失败: conversation_id=%s', conversation_id)
        for event in observations():
            yield event
        for pending in turn.pending_actions:
            yield {'type': 'approval_required', 'action': pending}
        if platform is not None:
            for pending in await anyio.to_thread.run_sync(self.audit_store.get_pending_actions, conversation_id):
                if pending['tool_name'] == PLATFORM_SERVER:
                    yield {'type': 'approval_required', 'action': pending}
        if evidence is not None:
            yield {'type': 'knowledge', 'evidence': evidence.snapshot()[1]}
        if loads is not None and loads.snapshot() != last_skills:
            yield {'type': 'skills', 'skills': loads.snapshot(), 'mode': 'on_demand'}
        yield {'type': 'usage', 'usage': usage}
        if failure:
            raise failure

    def delete_conversation(self, conversation_id):
        directory = self.conversation_directory(conversation_id)
        checkpoint = Path(self.settings.checkpoint_path)
        if checkpoint.exists():
            from langgraph.checkpoint.sqlite import SqliteSaver
            with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
                saver.setup()
                saver.delete_thread(conversation_id)
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)

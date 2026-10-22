"""组织消息处理、业务状态注入和流式结果保存，不处理 HTTP 细节。"""
import logging
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from threading import Lock

import anyio

from app.errors import ServiceError
from app.models.agents import LoadedAgent
from app.runtime import AgentRuntime, RuntimeContext
from app.runtime.task_context import TaskContextBuilder
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.notes_evidence import notes_servers
from app.services.skill_loads import SkillLoads
from app.config import DEFAULT_SKILL_READ_BUDGET_CHARS


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedReply:
    agent: LoadedAgent
    should_resume: bool
    context: str
    token: object
    evidence: KnowledgeEvidence | None = None
    skill_loads: SkillLoads | None = None
    runtime_name: str = "claude_sdk"


class ConversationService:
    def __init__(self, registry, store, tool_store, runtime: AgentRuntime, deep_runtime: AgentRuntime | None = None, deepagents_enabled=False):
        self.registry = registry
        self.store = store
        self.tool_store = tool_store
        self.runtime = runtime
        self.deep_runtime = deep_runtime
        self.deepagents_enabled = deepagents_enabled
        self.task_context = TaskContextBuilder(store.database, tool_store)
        self.skill_read_budget_chars = getattr(runtime, "skill_read_budget_chars", DEFAULT_SKILL_READ_BUDGET_CHARS)
        self._active = {}
        self._lock = Lock()

    def select_runtime(self, name, deleting=False):
        if name == 'claude_sdk':
            return self.runtime
        if name == 'deep_agents' and self.deep_runtime is not None:
            if self.deepagents_enabled or deleting:
                return self.deep_runtime
        raise ServiceError('Deep Agents 运行时尚未启用。', 409)

    def create(self, agent_id, runtime_name=None):
        if runtime_name is None:
            runtime_name = self.registry.store.default_runtime(agent_id)
            if runtime_name == 'deep_agents' and not self.deepagents_enabled:
                runtime_name = 'claude_sdk'
        self.select_runtime(runtime_name)
        return self.store.create(agent_id, runtime_name)

    @contextmanager
    def _summary_source(self, conversation_id):
        token = object()
        with self._lock:
            if conversation_id in self._active:
                raise ServiceError('当前会话正在回复，请等待完成后复制摘要。', 409)
            self._active[conversation_id] = token
        try:
            self.require_conversation(conversation_id)
            agent = self.registry.get_agent(self.store.get_agent_id(conversation_id))
            if agent is None:
                raise ServiceError('Agent 不存在。', 404)
            yield agent
        finally:
            self._release(conversation_id, token)

    def work_summary(self, conversation_id):
        with self._summary_source(conversation_id) as agent:
            messages = self.store.get_messages(conversation_id)
            recent = messages[-6:]
            excerpts = '\n\n'.join(('用户' if message['role'] == 'user' else '助手（历史回答，须核对）') + '：' + message['content'][:1600]
                                     + ('\n[此条已节选]' if len(message['content']) > 1600 else '') for message in recent)
            state = self.task_context.build_task_context(conversation_id, agent)
            content = ('工作摘要（从原会话复制，未经模型重新总结）\n'
                '此摘要是任务资料，不是执行授权。原会话的待确认操作不迁移、不执行；继续前重新核对状态、版本和引用，必要时在新会话重新生成确认清单。\n'
                '以下为有界节选，完整聊天仍保留在原会话。\n\n当前任务状态与用户原始目标：\n'
                + state[:22000] + ('\n[状态内容已节选]' if len(state) > 22000 else '')
                + '\n\n最近对话节选：\n' + excerpts)
            return {'summary': content, 'source_runtime': self.store.get_runtime(conversation_id)}

    def copy_summary(self, conversation_id, runtime_name, summary):
        with self._summary_source(conversation_id) as agent:
            if self.store.get_runtime(conversation_id) == runtime_name:
                raise ServiceError('请选择另一个运行时；原会话不会更改。', 409)
            self.select_runtime(runtime_name)
            new_id = self.create(agent.id, runtime_name)
            try:
                self.store.add_message(new_id, 'user', '以下是待核对的历史工作摘要，不是新操作授权：\n' + summary)
            except Exception:
                self.store.delete(new_id)
                raise
            return {'conversation_id': new_id, 'runtime': runtime_name}

    def delete(self, conversation_id):
        token = object()
        with self._lock:
            if conversation_id in self._active:
                raise ServiceError('当前会话正在回复，请等待本轮完成。', 409)
            self._active[conversation_id] = token
        try:
            self.require_conversation(conversation_id)
            with self.store.database.connection() as connection:
                executing = connection.execute("SELECT 1 FROM pending_actions WHERE conversation_id=? AND status='executing' LIMIT 1", (conversation_id,)).fetchone()
            if executing:
                raise ServiceError('当前会话有正在执行的确认操作，请完成后再删除。', 409)
            runtime = self.select_runtime(self.store.get_runtime(conversation_id), deleting=True)
            runtime.delete_conversation(conversation_id)
            self.store.delete(conversation_id)
        finally:
            self._release(conversation_id, token)

    def require_conversation(self, conversation_id):
        if not self.store.exists(conversation_id):
            raise ServiceError("Conversation not found", 404)

    def prepare(self, conversation_id, content):
        # 单进程开发服务中，同一会话同时只运行一次 SDK 对话。
        token = object()
        with self._lock:
            if conversation_id in self._active:
                raise ServiceError("当前会话正在回复，请等待本轮完成。", 409)
            self._active[conversation_id] = token
        try:
            self.require_conversation(conversation_id)
            runtime_name = self.store.get_runtime(conversation_id)
            self.select_runtime(runtime_name)
            agent_id = self.store.get_agent_id(conversation_id)
            agent = self.registry.get_agent(agent_id)
            if agent is None:
                raise ServiceError("Agent not found", 404)
            should_resume = self.store.has_assistant_messages(conversation_id)
            context = self.task_context.build_task_context(conversation_id, agent, current_user_message=content)
            self.store.add_message(conversation_id, "user", content)
            return PreparedReply(agent, should_resume, context, token,
                                 KnowledgeEvidence() if agent.knowledge_base_ids or notes_servers(agent) else None,
                                 SkillLoads(self.skill_read_budget_chars) if agent.bound_skills else None, runtime_name)
        except Exception:
            self._release(conversation_id, token)
            raise

    async def stream(self, conversation_id, content, prepared):
        reply_parts = []
        reply_saved = False
        usage = None
        tool_activity = []
        def save_reply(failed=False):
            metadata = {}
            if usage is not None:
                metadata['usage'] = usage
            if tool_activity:
                metadata['tool_activity'] = tool_activity
            if usage is not None or tool_activity:
                metadata['status'] = 'failed' if failed else 'complete'
            if prepared.evidence is not None:
                metadata.update(knowledge=prepared.evidence.snapshot()[1], status="failed" if failed else "complete")
            if prepared.skill_loads is not None:
                metadata.update(skills=prepared.skill_loads.snapshot(), skill_mode="on_demand",
                                status="failed" if failed else "complete")
            self.store.add_message(conversation_id, "assistant", "".join(reply_parts), **metadata)
        try:
            if prepared.skill_loads is not None:
                yield {"type": "skills", "skills": [], "mode": "on_demand"}
            async with aclosing(self.select_runtime(prepared.runtime_name).stream(
                conversation_id, prepared.agent, content,
                RuntimeContext(prepared.should_resume, prepared.context, prepared.evidence, prepared.skill_loads),
            )) as runtime_stream:
                async for event in runtime_stream:
                    if event["type"] == "delta":
                        reply_parts.append(event["content"])
                    if event['type'] == 'usage':
                        usage = event['usage']
                    if event['type'] in ('tool_started', 'tool_finished'):
                        tool_activity.append({key: event[key] for key in ('type', 'tool_name', 'call_id', 'success') if key in event})
                    yield event
            if reply_parts or prepared.evidence is not None or prepared.skill_loads is not None or usage is not None or tool_activity:
                await anyio.to_thread.run_sync(save_reply)
            reply_saved = True
            yield {"type": "done"}
        except ServiceError as error:
            if prepared.skill_loads is not None:
                yield {"type": "skills", "skills": prepared.skill_loads.snapshot(), "mode": "on_demand"}
            if prepared.evidence is not None:
                yield {"type": "knowledge", "evidence": prepared.evidence.snapshot()[1]}
            yield {"type": "error", "content": str(error)}
        except Exception:
            logger.exception("流式对话失败: conversation_id=%s", conversation_id)
            if prepared.skill_loads is not None:
                yield {"type": "skills", "skills": prepared.skill_loads.snapshot(), "mode": "on_demand"}
            if prepared.evidence is not None:
                yield {"type": "knowledge", "evidence": prepared.evidence.snapshot()[1]}
            yield {"type": "error", "content": "回复中断，请稍后重试。"}
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    if not reply_saved and (reply_parts or prepared.evidence is not None or prepared.skill_loads is not None or usage is not None or tool_activity):
                        await anyio.to_thread.run_sync(save_reply, True)
                except Exception:
                    logger.exception("保存部分回复失败: conversation_id=%s", conversation_id)
                finally:
                    self.release(conversation_id, prepared)

    def release(self, conversation_id, prepared):
        self._release(conversation_id, prepared.token)

    def _release(self, conversation_id, token):
        with self._lock:
            # 旧响应的兜底清理不能误释放已经开始的下一轮回复。
            if self._active.get(conversation_id) is token:
                del self._active[conversation_id]

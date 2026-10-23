"""组织消息处理、业务状态注入和流式结果保存，不处理 HTTP 细节。"""
import logging
from contextlib import aclosing
from dataclasses import dataclass
from threading import Lock

import anyio

from app.errors import ServiceError
from app.models.agents import LoadedAgent
from app.runtime import AgentRuntime, RuntimeContext
from app.runtime.task_context import TaskContextBuilder
from app.services.continuation import MAX_CONTINUATIONS, continuation_notice
from app.services.knowledge_evidence import KnowledgeEvidence
from app.storage.tool_store import decode_action
from app.platform.files import FileService
from app.services.notes_evidence import notes_servers
from app.services.skill_loads import SkillLoads
from app.config import DEFAULT_SKILL_READ_BUDGET_CHARS


logger = logging.getLogger(__name__)
ARCHIVED = '这个会话由已停用的 Claude SDK 运行时创建，只能查看。请新建会话继续。'


@dataclass(frozen=True)
class PreparedReply:
    agent: LoadedAgent
    should_resume: bool
    context: str
    token: object
    evidence: KnowledgeEvidence | None = None
    skill_loads: SkillLoads | None = None
    images: tuple = ()


class ConversationService:
    def __init__(self, registry, store, tool_store, runtime: AgentRuntime):
        self.registry = registry
        self.store = store
        self.tool_store = tool_store
        self.runtime = runtime
        self.task_context = TaskContextBuilder(store.database, tool_store)
        self.skill_read_budget_chars = getattr(runtime, "skill_read_budget_chars", DEFAULT_SKILL_READ_BUDGET_CHARS)
        self._active = {}
        self._lock = Lock()

    def archived(self, conversation_id):
        # Conversations from the retired Claude SDK runtime keep their messages but are not continued:
        # their working context lived in that runtime's own session files.
        return self.store.get_runtime(conversation_id) == 'claude_sdk'

    def create(self, agent_id):
        return self.store.create(agent_id)

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
            if not self.archived(conversation_id):
                self.runtime.delete_conversation(conversation_id)
            self.store.delete(conversation_id)
        finally:
            self._release(conversation_id, token)

    def require_conversation(self, conversation_id):
        if not self.store.exists(conversation_id):
            raise ServiceError("Conversation not found", 404)

    def prepare(self, conversation_id, content, attachment_ids=()):
        def user_input(agent):
            images = self._message_images(conversation_id, list(attachment_ids))
            names = {image['file_id']: image['filename'] for image in images}
            metadata = {'attachments': [{'id': file_id, 'filename': names[file_id]} for file_id in attachment_ids]} if attachment_ids else {}
            return content, 'user', metadata, content, tuple(images)
        return self._prepare(conversation_id, user_input)

    def _message_images(self, conversation_id, attachment_ids):
        if not attachment_ids:
            return []
        supports = getattr(self.runtime, 'supports_images', None)
        if supports is None or not supports():
            raise ServiceError('当前模型不支持图片。请把 WORKBENCH_DEEPAGENTS_MODEL 设为支持图片输入的模型，例如 deepseek-v4-flash。', 422)
        return FileService(self.store.database).model_images(conversation_id, attachment_ids)

    def prepare_continuation(self, conversation_id, action_id):
        """Resume after the user decided this turn's actions; the input is a platform notice built from records."""
        def notice(agent):
            actions, reason = self._continuation_batch(conversation_id, action_id)
            if reason:
                raise ServiceError(reason, 409)
            return continuation_notice(actions), 'platform', {'action_ids': [action['id'] for action in actions]}, None, ()
        prepared = self._prepare(conversation_id, notice)
        return prepared, self.store.get_messages(conversation_id)[-1]['content']

    def continuation_available(self, action):
        return self._continuation_batch(action['conversation_id'], action['id'])[1] is None

    def _continuation_batch(self, conversation_id, action_id):
        """Return (this turn's decided, unreported actions, None) or (None, reason). Reads records only."""
        with self.store.database.connection() as connection:
            action = connection.execute('SELECT * FROM pending_actions WHERE id=? AND conversation_id=?',
                                        (action_id, conversation_id)).fetchone()
            if action is None:
                return None, '当前会话中没有这条操作。'
            last_input = connection.execute(
                "SELECT created_at FROM messages WHERE conversation_id=? AND role IN ('user','platform') ORDER BY id DESC LIMIT 1",
                (conversation_id,)).fetchone()
            # A newer message means the conversation moved on; the result reaches the next turn's state instead.
            if last_input is None or last_input['created_at'] > action['created_at']:
                return None, '这条操作之后会话已有新消息，不再自动继续。'
            turn = connection.execute('SELECT * FROM pending_actions WHERE conversation_id=? AND created_at>=? ORDER BY created_at, rowid',
                                      (conversation_id, last_input['created_at'])).fetchall()
            if any(row['status'] in ('pending', 'executing') for row in turn):
                return None, '本轮还有未处理完的待确认操作，全部处理后再继续。'
            reported = {row[0] for row in connection.execute(
                "SELECT j.value FROM messages m, json_each(m.metadata, '$.action_ids') j WHERE m.conversation_id=? AND m.role='platform'",
                (conversation_id,))}
            if action_id in reported:
                return None, '这条操作的结果已经交给 Agent，不会重复继续。'
            last_user = connection.execute("SELECT COALESCE(MAX(id), 0) FROM messages WHERE conversation_id=? AND role='user'",
                                           (conversation_id,)).fetchone()[0]
            chain = connection.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=? AND role='platform' AND id>?",
                                       (conversation_id, last_user)).fetchone()[0]
            if chain >= MAX_CONTINUATIONS:
                return None, f'已连续自动继续 {MAX_CONTINUATIONS} 次，请发送消息后再继续。'
            return [decode_action(row) for row in turn if row['id'] not in reported], None

    def _prepare(self, conversation_id, build_input):
        # 单进程开发服务中，同一会话同时只运行一次 SDK 对话。
        token = object()
        with self._lock:
            if conversation_id in self._active:
                raise ServiceError("当前会话正在回复，请等待本轮完成。", 409)
            self._active[conversation_id] = token
        try:
            self.require_conversation(conversation_id)
            if self.archived(conversation_id):
                raise ServiceError(ARCHIVED, 409)
            agent_id = self.store.get_agent_id(conversation_id)
            agent = self.registry.get_agent(agent_id)
            if agent is None:
                raise ServiceError("Agent not found", 404)
            content, role, metadata, current_user_message, images = build_input(agent)
            should_resume = self.store.has_assistant_messages(conversation_id)
            context = self.task_context.build_task_context(conversation_id, agent, current_user_message=current_user_message)
            self.store.add_message(conversation_id, role, content, **metadata)
            return PreparedReply(agent, should_resume, context, token,
                                 KnowledgeEvidence() if agent.knowledge_base_ids or notes_servers(agent) else None,
                                 SkillLoads(self.skill_read_budget_chars) if agent.bound_skills else None, images)
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
            async with aclosing(self.runtime.stream(
                conversation_id, prepared.agent, content,
                RuntimeContext(prepared.should_resume, prepared.context, prepared.evidence, prepared.skill_loads, prepared.images),
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

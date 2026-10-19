"""组织消息处理、业务状态注入和流式结果保存，不处理 HTTP 细节。"""
import logging
from contextlib import aclosing
from dataclasses import dataclass
from threading import Lock

import anyio

from app.errors import ServiceError
from app.models.agents import LoadedAgent
from app.services.business_context import build_business_context
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.notes_evidence import notes_servers
from app.services.skill_loads import SkillLoads


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedReply:
    agent: LoadedAgent
    should_resume: bool
    context: str
    token: object
    evidence: KnowledgeEvidence | None = None
    skill_loads: SkillLoads | None = None


class ConversationService:
    def __init__(self, registry, store, tool_store, runtime):
        self.registry = registry
        self.store = store
        self.tool_store = tool_store
        self.runtime = runtime
        self._active = {}
        self._lock = Lock()

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
            agent_id = self.store.get_agent_id(conversation_id)
            agent = self.registry.get_agent(agent_id)
            if agent is None:
                raise ServiceError("Agent not found", 404)
            should_resume = self.store.has_assistant_messages(conversation_id)
            latest_action = self.tool_store.get_last_resolved_action(conversation_id)
            context = build_business_context(latest_action)
            self.store.add_message(conversation_id, "user", content)
            return PreparedReply(agent, should_resume, context, token,
                                 KnowledgeEvidence() if agent.knowledge_base_ids or notes_servers(agent) else None,
                                 SkillLoads() if agent.bound_skills else None)
        except Exception:
            self._release(conversation_id, token)
            raise

    async def stream(self, conversation_id, content, prepared):
        reply_parts = []
        reply_saved = False
        options = {"business_context": prepared.context}
        if prepared.evidence is not None:
            options["knowledge_evidence"] = prepared.evidence
        if prepared.skill_loads is not None:
            options["skill_loads"] = prepared.skill_loads

        def save_reply(failed=False):
            metadata = {}
            if prepared.evidence is not None:
                metadata = {"knowledge": prepared.evidence.snapshot()[1], "status": "failed" if failed else "complete"}
            if prepared.skill_loads is not None:
                metadata.update(skills=prepared.skill_loads.snapshot(), skill_mode="on_demand",
                                status="failed" if failed else "complete")
            self.store.add_message(conversation_id, "assistant", "".join(reply_parts), **metadata)
        try:
            if prepared.skill_loads is not None:
                yield {"type": "skills", "skills": [], "mode": "on_demand"}
            async with aclosing(self.runtime.stream_reply(
                conversation_id, prepared.agent, content, prepared.should_resume,
                **options,
            )) as runtime_stream:
                async for event in runtime_stream:
                    if event["type"] == "delta":
                        reply_parts.append(event["content"])
                    yield event
            if reply_parts or prepared.evidence is not None or prepared.skill_loads is not None:
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
                    if not reply_saved and (reply_parts or prepared.evidence is not None or prepared.skill_loads is not None):
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

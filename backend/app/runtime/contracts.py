"""Stable event envelopes; payloads keep the existing SSE fields and ordering."""
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol, Required, TypedDict, runtime_checkable

from app.models.agents import LoadedAgent
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.skill_loads import SkillLoads


class RuntimeEvent(TypedDict, total=False):
    type: Required[Literal['delta', 'tool_started', 'tool_finished', 'knowledge', 'skills',
                  'approval_required', 'usage', 'error', 'done']]
    content: str
    action: dict[str, Any]
    evidence: dict[str, Any]
    skills: list[dict[str, Any]]
    mode: Literal['on_demand']
    usage: dict[str, Any]
    tool_name: str
    call_id: str
    success: bool


@dataclass(frozen=True)
class RuntimeContext:
    should_resume: bool = False
    business_context: str = ''
    evidence: KnowledgeEvidence | None = None
    skill_loads: SkillLoads | None = None


@runtime_checkable
class AgentRuntime(Protocol):
    def stream(self, conversation_id: str, agent: LoadedAgent, user_message: str,
               context: RuntimeContext) -> AsyncIterator[RuntimeEvent]: ...

    def delete_conversation(self, conversation_id: str) -> None: ...

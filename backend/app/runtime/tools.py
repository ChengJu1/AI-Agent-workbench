"""Bind shared business services to one turn, without duplicating approval policies."""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio

from app.errors import ServiceError
from app.platform.service import SERVER_NAME as PLATFORM_SERVER
from app.services.knowledge_service import KnowledgeService
from app.services.mcp_audit import McpAuditTracker
from app.services.notes_evidence import NotesEvidenceTracker, notes_servers
from app.storage.agent_store import AgentStore
from app.storage.knowledge_store import KnowledgeStore
from app.storage.skill_store import SkillStore
from app.tools.external_tools import ExternalToolServer
from app.tools.knowledge_tools import KnowledgeToolsService, SERVER_NAME as KNOWLEDGE_SERVER
from app.tools.mcp_adapter import McpAdapter, build_external_tools
from app.tools.platform_tools import platform_definitions
from app.tools.runtime_adapters import to_langchain
from app.tools.skill_tools import SkillToolsService, SERVER_NAME as SKILL_SERVER
from app.tools.team_tools import SERVER_NAME as TEAM_SERVER
from app.tools.timesheet_tools import TimesheetToolsService, TOOL_NAME as TIMESHEET_SERVER


@dataclass
class TurnTools:
    groups: dict
    external: dict
    allowed_external: list
    audit: McpAuditTracker
    pending_actions: list
    prompt: str = ''
    tools: list = field(default_factory=list)

    @property
    def names(self):
        return {tool.name for tool in self.tools}

    @asynccontextmanager
    async def langchain(self):
        proxies = []
        try:
            for name, config in self.external.items():
                prefix = f'mcp__{name}__'
                actions = [item[len(prefix):] for item in self.allowed_external if item.startswith(prefix)]
                proxy = ExternalToolServer(name, config, actions, self.audit)
                proxies.append(proxy)
                self.tools.extend(await proxy.to_langchain())
            for name, definitions in self.groups.items():
                self.tools.extend(to_langchain(definitions, name))
            if len(self.names) != len(self.tools):
                raise ServiceError('工具名称冲突。', 409)
            yield self
        finally:
            with anyio.CancelScope(shield=True):
                for proxy in reversed(proxies):
                    await proxy.close()


class RuntimeTools:
    def __init__(self, audit_store):
        self.audit_store = audit_store
        self.platform = None
        self.teams = None
        self.mcp_adapter = McpAdapter()
        self.timesheets = TimesheetToolsService(store=audit_store)
        self.skills = SkillToolsService(SkillStore(audit_store.database), audit_store)
        self.knowledge = KnowledgeToolsService(KnowledgeService(KnowledgeStore(audit_store.database)),
                                             AgentStore(audit_store.database), audit_store)

    def prepare(self, conversation_id, agent, evidence, loads):
        external, allowed = build_external_tools(agent, self.audit_store.database, self.mcp_adapter)
        groups = {}
        def register(name, definitions):
            if name in external or name in groups:
                raise ServiceError('MCP 名称与共享业务工具冲突。', 409)
            groups[name] = definitions
        if agent.platform_capabilities:
            if self.platform is None:
                raise ServiceError('平台基础能力未初始化。', 503)
            register(PLATFORM_SERVER, platform_definitions(self.platform, conversation_id, agent)[0])
        if agent.bound_skills:
            register(SKILL_SERVER, self.skills.definitions(conversation_id, agent, loads))
        if agent.knowledge_base_ids:
            register(KNOWLEDGE_SERVER, self.knowledge.definitions(conversation_id, agent, evidence))
        definitions, pending = self.timesheets.definitions(conversation_id, agent)
        if definitions:
            register(TIMESHEET_SERVER, definitions)
        team, team_text = self.teams.prepare(conversation_id, agent, pending) if self.teams is not None else ([], '')
        if team:
            register(TEAM_SERVER, team)
        observer = NotesEvidenceTracker(evidence, notes_servers(agent)).capture if evidence is not None else None
        audit = McpAuditTracker(self.audit_store, conversation_id, agent.id, allowed, observer)
        return TurnTools(groups, external, allowed, audit, pending, team_text)

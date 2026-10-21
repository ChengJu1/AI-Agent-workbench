"""在应用启动时创建共享服务，测试可以注入临时数据库和假的 Runtime。"""
from app.config import Settings
from app.runtime.deep_agents import DeepAgentsRuntime
from app.platform.service import PlatformService
from app.services.tracking_service import TrackingService
from app.kits.registry import kits
from app.services.build_service import AgentBuildService
from app.services.agent_registry import AgentRegistry
from app.services.agent_catalog import AgentCatalog
from app.services.approval_service import ApprovalService
from app.services.claude_runtime import ClaudeRuntimeService
from app.services.conversation_service import ConversationService
from app.services.mcp_discovery import McpDiscoveryService
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_evaluation import RetrievalEvaluationService
from app.storage.agent_store import AgentStore
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.knowledge_store import KnowledgeStore
from app.storage.tool_store import ToolStore
from app.storage.skill_store import SkillStore
from app.tools.cli_adapter import CliAdapter
from app.tools.timesheet_tools import TimesheetToolsService
from app.tools.knowledge_tools import KnowledgeToolsService


class Services:
    def __init__(self, registry, store, tool_store, cli_adapter, runtime, settings=None):
        self.agent_builds = AgentBuildService(store.database, skill_budget_chars=runtime.skill_read_budget_chars if isinstance(runtime, ClaudeRuntimeService) else 80000)
        self.skills = SkillStore(store.database)
        self.registry = AgentCatalog(registry, AgentStore(store.database), self.skills)
        self.store = store
        self.tool_store = tool_store
        self.deep_agents = DeepAgentsRuntime(settings or Settings(database_path=store.database.path), tool_store)
        self.conversations = ConversationService(self.registry, store, tool_store, runtime, self.deep_agents, self.deep_agents.settings.deepagents_enabled)
        self.platform = PlatformService(store.database, self.registry, store, tool_store)
        self.tracking = TrackingService(self.platform)
        self.platform.tracking = self.tracking
        self.kits = {kit.ID: kit.build(store.database, self.platform) for kit in kits()}
        self.platform.kits = self.kits
        self.deep_agents.tool_services.platform = self.platform
        if isinstance(runtime, ClaudeRuntimeService):
            runtime.context_settings = self.deep_agents.settings
            runtime._platform_tools = self.platform
            self.deep_agents.tool_services.timesheets = runtime._tools_service
            self.deep_agents.tool_services.skills = runtime._skill_tools
            if runtime._knowledge_tools is not None:
                self.deep_agents.tool_services.knowledge = runtime._knowledge_tools
            self.deep_agents.tool_services.mcp_adapter = runtime._mcp_adapter
        self.approvals = ApprovalService(self.registry, tool_store, cli_adapter, platform=self.platform)
        self.mcp_discovery = McpDiscoveryService()
        self.knowledge = KnowledgeService(KnowledgeStore(store.database))
        self.retrieval_evaluation = RetrievalEvaluationService(self.knowledge.store)


def build_services(settings):
    registry = AgentRegistry(settings.agents_directory)
    database = Database(settings.database_path)
    database.initialize()
    store = ConversationStore(database)
    tool_store = ToolStore(database)
    adapter = CliAdapter()
    tools = TimesheetToolsService(adapter=adapter, store=tool_store)
    knowledge = KnowledgeService(KnowledgeStore(database))
    knowledge.reindex_outdated()
    knowledge_tools = KnowledgeToolsService(
        knowledge, AgentStore(database), tool_store,
    )
    runtime = ClaudeRuntimeService(tools_service=tools, audit_store=tool_store, knowledge_tools=knowledge_tools,
                                   skill_read_budget_chars=settings.skill_read_budget_chars)
    return Services(registry, store, tool_store, adapter, runtime, settings)

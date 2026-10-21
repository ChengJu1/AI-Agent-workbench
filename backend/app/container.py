"""在应用启动时创建共享服务，测试可以注入临时数据库和假的 Runtime。"""
from app.platform.service import PlatformService
from app.services.tracking_service import TrackingService
from app.services.application_actions import ApplicationActions
from app.storage.application_store import ApplicationStore
from app.storage.profile_store import ProfileStore
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
    def __init__(self, registry, store, tool_store, cli_adapter, runtime):
        self.agent_builds = AgentBuildService(store.database, skill_budget_chars=runtime.skill_read_budget_chars if isinstance(runtime, ClaudeRuntimeService) else 80000)
        self.skills = SkillStore(store.database)
        self.registry = AgentCatalog(registry, AgentStore(store.database), self.skills)
        self.store = store
        self.tool_store = tool_store
        self.conversations = ConversationService(self.registry, store, tool_store, runtime)
        self.platform = PlatformService(store.database, self.registry, store, tool_store)
        self.tracking = TrackingService(self.platform)
        self.platform.tracking = self.tracking
        self.profiles = ProfileStore(store.database)
        self.applications = ApplicationStore(store.database)
        self.platform.application_actions = ApplicationActions(self.applications, self.profiles, self.platform)
        if isinstance(runtime, ClaudeRuntimeService):
            runtime._platform_tools = self.platform
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
    return Services(registry, store, tool_store, adapter, runtime)

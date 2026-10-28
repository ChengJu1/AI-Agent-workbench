"""在应用启动时创建共享服务，测试可以注入临时数据库和假的 Runtime。"""
from app.config import Settings
from app.runtime.deep_agents import DeepAgentsRuntime, chat_model
from app.platform.service import PlatformService
from app.services.tracking_service import TrackingService
from app.services.team_service import TeamService
from app.kits.registry import kits
from app.services.build_generator import BuildGenerator
from app.services.build_service import AgentBuildService
from app.services.agent_registry import AgentRegistry
from app.services.agent_catalog import AgentCatalog
from app.services.approval_service import ApprovalService
from app.services.conversation_service import ConversationService
from app.services.mcp_discovery import McpDiscoveryService
from app.services.embeddings import LocalEmbedder, LocalReranker
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_evaluation import RetrievalEvaluationService
from app.storage.agent_store import AgentStore
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.knowledge_store import KnowledgeStore
from app.storage.tool_store import ToolStore
from app.storage.skill_store import SkillStore
from app.storage.team_store import TeamStore
from app.tools.cli_adapter import CliAdapter
from app.tools.timesheet_tools import TimesheetToolsService
from app.tools.knowledge_tools import KnowledgeToolsService


class Services:
    def __init__(self, registry, store, tool_store, cli_adapter, runtime=None, settings=None):
        """`runtime` replaces Deep Agents for conversations (tests inject a fake one)."""
        self.skills = SkillStore(store.database)
        self.registry = AgentCatalog(registry, AgentStore(store.database), self.skills)
        self.store = store
        self.tool_store = tool_store
        self.deep_agents = DeepAgentsRuntime(settings or Settings(database_path=store.database.path), tool_store)
        settings = self.deep_agents.settings
        self.agent_builds = AgentBuildService(store.database, BuildGenerator(lambda: chat_model(settings)),
                                              skill_budget_chars=settings.skill_read_budget_chars)
        self.teams = TeamService(self.registry, TeamStore(store.database))
        self.conversations = ConversationService(self.registry, store, tool_store, runtime or self.deep_agents)
        self.platform = PlatformService(store.database, self.registry, store, tool_store)
        self.tracking = TrackingService(self.platform)
        self.platform.tracking = self.tracking
        self.kits = {kit.ID: kit.build(store.database, self.platform) for kit in kits()}
        self.platform.kits = self.kits
        self.deep_agents.tool_services.platform = self.platform
        self.approvals = ApprovalService(self.registry, tool_store, cli_adapter, platform=self.platform)
        self.mcp_discovery = McpDiscoveryService()
        embedder = (LocalEmbedder(settings.knowledge_embedding_model, settings.embedding_directory)
                    if settings.knowledge_embedding_model else None)
        reranker = (LocalReranker(settings.knowledge_rerank_model, settings.embedding_directory)
                    if settings.knowledge_rerank_model else None)
        self.knowledge = KnowledgeService(KnowledgeStore(store.database), embedder, reranker)
        self.retrieval_evaluation = RetrievalEvaluationService(self.knowledge.store, self.knowledge)
        self.deep_agents.tool_services.knowledge.knowledge = self.knowledge


def build_services(settings):
    registry = AgentRegistry(settings.agents_directory)
    database = Database(settings.database_path)
    database.initialize()
    store = ConversationStore(database)
    tool_store = ToolStore(database)
    adapter = CliAdapter()
    services = Services(registry, store, tool_store, adapter, settings=settings)
    services.knowledge.reindex_outdated()
    services.knowledge.schedule_vectors()
    tools = services.deep_agents.tool_services
    tools.timesheets = TimesheetToolsService(adapter=adapter, store=tool_store)
    tools.knowledge = KnowledgeToolsService(services.knowledge, AgentStore(database), tool_store)
    return services

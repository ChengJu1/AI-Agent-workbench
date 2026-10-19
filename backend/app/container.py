"""在应用启动时创建共享服务，测试可以注入临时数据库和假的 Runtime。"""
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
        self.agent_builds = AgentBuildService(store.database)
        self.skills = SkillStore(store.database)
        self.registry = AgentCatalog(registry, AgentStore(store.database), self.skills)
        self.store = store
        self.tool_store = tool_store
        self.conversations = ConversationService(self.registry, store, tool_store, runtime)
        self.approvals = ApprovalService(self.registry, tool_store, cli_adapter)
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

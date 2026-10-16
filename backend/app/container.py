"""在应用启动时创建共享服务，测试可以注入临时数据库和假的 Runtime。"""
from app.services.agent_registry import AgentRegistry
from app.services.approval_service import ApprovalService
from app.services.claude_runtime import ClaudeRuntimeService
from app.services.conversation_service import ConversationService
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.tool_store import ToolStore
from app.tools.cli_adapter import CliAdapter
from app.tools.timesheet_tools import TimesheetToolsService


class Services:
    def __init__(self, registry, store, tool_store, cli_adapter, runtime):
        self.registry = registry
        self.store = store
        self.tool_store = tool_store
        self.conversations = ConversationService(registry, store, tool_store, runtime)
        self.approvals = ApprovalService(registry, tool_store, cli_adapter)


def build_services(settings):
    registry = AgentRegistry(settings.agents_directory)
    database = Database(settings.database_path)
    database.initialize()
    store = ConversationStore(database)
    tool_store = ToolStore(database)
    adapter = CliAdapter()
    tools = TimesheetToolsService(adapter=adapter, store=tool_store)
    runtime = ClaudeRuntimeService(tools_service=tools, audit_store=tool_store)
    return Services(registry, store, tool_store, adapter, runtime)

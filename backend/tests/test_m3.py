# 验证 M3 的制度存储、MCP 工具、Manifest 配置、Runtime 审计和错误边界。
# 测试使用临时目录与临时数据库，不会写入正式 workbench.db。
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import asynccontextmanager
from mcp.types import CallToolResult, ListToolsResult, Tool

from claude_agent_sdk import (
    AssistantMessage,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from mcp.shared.memory import (
    create_connected_server_and_client_session,
)


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIRECTORY))


from app.agents import get_agent
from app.services.claude_runtime import ClaudeRuntimeService
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.tools.mcp_adapter import McpAdapter
from app.storage.policy_store import PolicyStore
from app.storage.tool_store import ToolStore
from mcp_servers.policy_server import policy_server


class EmptyToolSession:
    def __init__(self):
        self.server = {}
        self.allowed_tools = []
        self.pending_actions = []


class EmptyTimesheetToolsService:
    def create_session(self, conversation_id, agent):
        return EmptyToolSession()


class M3TestCase(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        temporary_path = Path(self._temporary_directory.name)

        self._policies_directory = temporary_path / "policies"
        self._policies_directory.mkdir()
        self._policy_file = (
            self._policies_directory / "gpu-application.md"
        )
        self._policy_file.write_text(
            (
                "# GPU资源申请管理制度\n"
                "- 制度ID: GPU-001\n"
                "- 关键词: GPU、显卡、算力\n\n"
                "## 申请条件\n"
                "申请人需要提供项目计划并取得主管批准。\n"
            ),
            encoding="utf-8",
        )

        database_path = temporary_path / "test.db"
        database = Database(database_path)
        database.initialize()
        self.conversation_store = ConversationStore(database)
        self.tool_store = ToolStore(database)

        self.agent = get_agent("policy_qa_assistant")
        self.conversation_id = self.conversation_store.create(
            self.agent.id
        )

    def tearDown(self):
        self._temporary_directory.cleanup()

    def test_policy_store_searches_and_reads_policy(self):
        store = PolicyStore(self._policies_directory)

        search_result = store.search_policy("我需要申请GPU算力")
        self.assertEqual(search_result["status"], "success")
        self.assertEqual(len(search_result["matches"]), 1)
        self.assertEqual(
            search_result["matches"][0]["policy_id"],
            "GPU-001",
        )

        detail = store.get_policy_detail("GPU-001")
        self.assertEqual(
            detail["title"],
            "GPU资源申请管理制度",
        )
        self.assertEqual(
            detail["source"],
            "gpu-application.md",
        )
        self.assertIn("主管批准", detail["content"])

    def test_policy_store_returns_empty_matches(self):
        store = PolicyStore(self._policies_directory)

        result = store.search_policy("年假报销")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["message"], "没有找到相关制度")

    def test_policy_store_rejects_unknown_policy_id(self):
        store = PolicyStore(self._policies_directory)

        with self.assertRaisesRegex(ValueError, "制度ID不存在"):
            store.get_policy_detail("UNKNOWN-001")

    def test_policy_mcp_server_lists_and_calls_tools(self):
        async def call_tools():
            async with create_connected_server_and_client_session(
                policy_server
            ) as client:
                tools_result = await client.list_tools()
                tool_names = []

                for available_tool in tools_result.tools:
                    tool_names.append(available_tool.name)

                search_result = await client.call_tool(
                    "search_policy",
                    {"query": "GPU"},
                )
                detail_result = await client.call_tool(
                    "get_policy_detail",
                    {"policy_id": "GPU-001"},
                )

                return tool_names, search_result, detail_result

        results = asyncio.run(call_tools())
        tool_names = results[0]
        search_result = results[1]
        detail_result = results[2]

        self.assertIn("search_policy", tool_names)
        self.assertIn("get_policy_detail", tool_names)
        self.assertFalse(search_result.isError)
        self.assertFalse(detail_result.isError)
        self.assertIn("GPU-001", str(search_result.content))
        self.assertIn("gpu-application.md", str(detail_result.content))

    def test_mcp_adapter_uses_manifest_whitelist(self):
        servers, allowed_tools = McpAdapter().build(self.agent)

        self.assertIn("policy_server", servers)
        self.assertEqual(
            servers["policy_server"]["command"],
            sys.executable,
        )
        self.assertEqual(
            servers["policy_server"]["args"],
            ["-m", "mcp_servers.policy_server"],
        )
        self.assertEqual(
            allowed_tools,
            [
                "mcp__policy_server__search_policy",
                "mcp__policy_server__get_policy_detail",
            ],
        )

    @asynccontextmanager
    async def open_fixture_session(self, config):
        class Fixture:
            async def list_tools(self, cursor=None):
                return ListToolsResult(tools=[Tool(name=name, inputSchema={'type': 'object'})
                    for name in ('search_policy', 'get_policy_detail')])

            async def call_tool(self, name, arguments):
                return CallToolResult(content=[{'type': 'text', 'text': '{"status":"success"}'}],
                                      isError=name == 'get_policy_detail')
        yield Fixture()

    def test_runtime_records_successful_mcp_call(self):
        async def fake_query(prompt, options):
            async with create_connected_server_and_client_session(options.mcp_servers['policy_server']['instance']) as client:
                await client.call_tool('search_policy', {'query': 'GPU'})
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tool-call-1",
                        name="mcp__policy_server__search_policy",
                        input={"query": "GPU"},
                    )
                ],
                model="test-model",
            )
            yield UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id="tool-call-1",
                        content='{"status":"success"}',
                        is_error=False,
                    )
                ]
            )
            yield StreamEvent(
                uuid="event-1",
                session_id=self.conversation_id,
                event={
                    "type": "content_block_delta",
                    "delta": {
                        "type": "text_delta",
                        "text": "查询完成",
                    },
                },
            )

        runtime = ClaudeRuntimeService(
            tools_service=EmptyTimesheetToolsService(),
            audit_store=self.tool_store,
        )

        async def collect_events():
            events = []

            with patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "test-key"},
            ):
                with patch(
                    "app.services.claude_runtime.query",
                    fake_query,
                ), patch("app.tools.external_tools.open_mcp_session", self.open_fixture_session):
                    async for event in runtime.stream_reply(
                        self.conversation_id,
                        self.agent,
                        "查询GPU制度",
                        False,
                    ):
                        events.append(event)

            return events

        events = asyncio.run(collect_events())
        logs = self.tool_store.get_audit_logs(
            self.conversation_id
        )

        self.assertEqual(next(event["content"] for event in events if event["type"] == "delta"), "查询完成")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["tool_type"], "mcp")
        self.assertEqual(logs[0]["action"], "search_policy")
        self.assertEqual(logs[0]["status"], "success")

    def test_runtime_converts_mcp_failure_to_safe_error(self):
        async def failing_query(prompt, options):
            async with create_connected_server_and_client_session(options.mcp_servers['policy_server']['instance']) as client:
                await client.call_tool('get_policy_detail', {'policy_id': 'GPU-001'})
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tool-call-2",
                        name="mcp__policy_server__get_policy_detail",
                        input={"policy_id": "GPU-001"},
                    )
                ],
                model="test-model",
            )
            raise RuntimeError("private internal MCP error")

        runtime = ClaudeRuntimeService(
            tools_service=EmptyTimesheetToolsService(),
            audit_store=self.tool_store,
        )

        async def collect_events():
            with patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "test-key"},
            ):
                with patch(
                    "app.services.claude_runtime.query",
                    failing_query,
                ), patch("app.tools.external_tools.open_mcp_session", self.open_fixture_session):
                    with patch(
                        "app.services.claude_runtime.logger.exception"
                    ):
                        async for event in runtime.stream_reply(
                            self.conversation_id,
                            self.agent,
                            "查询GPU制度",
                            False,
                        ):
                            pass

        with self.assertRaisesRegex(
            RuntimeError,
            "MCP 工具服务暂时不可用，请稍后重试",
        ):
            asyncio.run(collect_events())

        logs = self.tool_store.get_audit_logs(
            self.conversation_id
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["tool_type"], "mcp")
        self.assertEqual(logs[0]["status"], "failed")
        self.assertEqual(
            logs[0]["error"],
            "MCP 工具调用失败",
        )
        self.assertNotIn(
            "private internal MCP error",
            logs[0]["error"],
        )


if __name__ == "__main__":
    unittest.main()

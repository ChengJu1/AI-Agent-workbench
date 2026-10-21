"""验证前端配置 Agent 的持久化、SDK 装配、输入边界和 MCP 工具发现。"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.agents import McpConnection
from app.services.mcp_discovery import McpDiscoveryService
from app.tools.mcp_adapter import McpAdapter


class CustomAgentsTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)

    def definition(self):
        return {
            "name": "我的制度助理", "description": "连接团队 MCP 服务",
            "system_prompt": "根据工具返回的内容回答，附带来源。",
            "tools": [{
                "type": "mcp", "name": "team_policy", "transport": "http",
                "url": "http://localhost:8059/mcp",
                "headers": {"Authorization": "Bearer test-private-token"},
                "actions": ["search_policy"],
            }],
        }

    def create_agent(self):
        response = self.client.post("/api/agents", json=self.definition())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("test-private-token", response.text)
        return response.json()

    def test_agent_creation_persists_and_is_available_without_restart(self):
        created = self.create_agent()
        response = self.client.get("/api/agents")
        self.assertIn(created, response.json())
        self.assertEqual(len(response.json()), 3)
        self.assertNotIn("test-private-token", response.text)
        agent = self.services.registry.get_agent(created["id"])
        self.assertEqual(agent.system_prompt, self.definition()["system_prompt"])
        self.assertEqual(agent.tools[0].actions, ["search_policy"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.get_agent(created["id"]), agent)

    def test_custom_agent_is_used_for_conversation_stream(self):
        created = self.create_agent()
        used_agents = []

        class Runtime:
            async def stream(self, conversation_id, agent, *args, **kwargs):
                used_agents.append(agent)
                yield {"type": "delta", "content": "使用自定义 Agent 回复"}

        self.services.conversations.runtime = Runtime()
        response = self.client.post("/api/conversations", json={"agent_id": created["id"]})
        conversation_id = response.json()["conversation_id"]
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages/stream", json={"content": "查询制度"}
        )
        self.assertIn('"type": "done"', response.text)
        self.assertEqual(used_agents[0].id, created["id"])
        self.assertEqual(used_agents[0].tools[0].name, "team_policy")

    def test_remote_mcp_configuration_and_tool_whitelist_reach_sdk(self):
        created = self.create_agent()
        agent = self.services.registry.get_agent(created["id"])
        servers, allowed = McpAdapter().build(agent)
        self.assertEqual(servers, {"team_policy": {
            "type": "http", "url": "http://localhost:8059/mcp",
            "headers": {"Authorization": "Bearer test-private-token"},
        }})
        self.assertEqual(allowed, ["mcp__team_policy__search_policy"])
        runtime = self.services.conversations.runtime
        options, audit_tools, session = runtime._build_options("test", agent, False, "")
        self.assertEqual(options.mcp_servers, servers)
        self.assertEqual(options.allowed_tools, allowed)
        self.assertEqual(audit_tools, allowed)
        self.assertEqual(session.allowed_tools, [])

    def test_sse_service_configuration_is_supported(self):
        definition = self.definition()
        definition["tools"][0]["transport"] = "sse"
        definition["tools"][0]["url"] = "https://mcp.example.com/sse"
        response = self.client.post("/api/agents", json=definition)
        agent = self.services.registry.get_agent(response.json()["id"])
        self.assertEqual(McpAdapter().build(agent)[0]["team_policy"]["type"], "sse")

    def test_mcp_tool_names_can_contain_dots(self):
        definition = self.definition()
        definition["tools"][0]["actions"] = ["policy.search"]
        response = self.client.post("/api/agents", json=definition)
        self.assertEqual(response.status_code, 201)
        agent = self.services.registry.get_agent(response.json()["id"])
        self.assertEqual(McpAdapter().build(agent)[1], ["mcp__team_policy__policy.search"])

    def test_invalid_definitions_are_rejected_without_registering_agents(self):
        mutations = [
            lambda d: d.update(name="   "),
            lambda d: d.update(system_prompt=""),
            lambda d: d.update(id="timesheet_assistant"),
            lambda d: d.update(tools=[]),
            lambda d: d["tools"].append(d["tools"][0].copy()),
            lambda d: d["tools"][0].update(actions=[]),
            lambda d: d["tools"][0].update(actions=["search_policy", "search_policy"]),
            lambda d: d["tools"][0].update(actions=["search; rm -rf"]),
            lambda d: d["tools"][0].update(name="bad__name"),
            lambda d: d["tools"][0].update(url="file:///private/file"),
            lambda d: d["tools"][0].update(url="http://user:password@host/mcp"),
            lambda d: d["tools"][0].update(transport="stdio", command="python", args=["-c", "print(1)"]),
            lambda d: d["tools"][0].update(headers={"Authorization": "token\r\nInjected: yes"}),
        ]
        for mutate in mutations:
            definition = self.definition()
            mutate(definition)
            with self.subTest(definition=definition):
                response = self.client.post("/api/agents", json=definition)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(self.client.get("/api/agents").json()), 2)

    def test_discovery_api_uses_connection_config_and_returns_tool_schema(self):
        tools = [{"name": "search_policy", "description": "查询制度", "input_schema": {"type": "object"}}]
        connection = {key: value for key, value in self.definition()["tools"][0].items()
                      if key not in ("type", "actions")}
        with patch.object(self.services.mcp_discovery, "list_tools", AsyncMock(return_value=tools)) as discover:
            response = self.client.post("/api/mcp/tools", json=connection)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), tools)
        self.assertEqual(discover.call_args.args[0].headers, connection["headers"])


class McpDiscoveryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_streamable_http_discovers_real_mcp_tool_schemas(self):
        server = FastMCP("test-tools", stateless_http=True, json_response=True)

        @server.tool()
        def search_policy(query: str) -> str:
            """查询制度。"""
            return query

        app = server.streamable_http_app()
        original_client = httpx.AsyncClient

        def make_client(**kwargs):
            return original_client(transport=httpx.ASGITransport(app=app), **kwargs)

        async with server.session_manager.run():
            with patch("app.services.mcp_discovery.httpx.AsyncClient", side_effect=make_client):
                tools = await McpDiscoveryService().list_tools(McpConnection(
                    name="policy", url="http://localhost:8059/mcp", transport="http"
                ))
        self.assertEqual([tool.name for tool in tools], ["search_policy"])
        self.assertIn("query", tools[0].input_schema["properties"])

    async def test_discovery_failure_does_not_expose_service_details(self):
        with patch("app.services.mcp_discovery.streamable_http_client", side_effect=RuntimeError("private-token")):
            with self.assertRaises(ServiceError) as raised:
                await McpDiscoveryService().list_tools(McpConnection(name="test", url="https://mcp.test/mcp"))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private-token", str(raised.exception))

    async def test_repeated_pagination_cursor_is_rejected(self):
        session = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=[], nextCursor="again")))
        with self.assertRaisesRegex(ValueError, "分页异常"):
            await McpDiscoveryService()._collect_tools(session)

"""验证绑定持久化、SDK 工具协议、对话装配及运行中的授权边界。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from mcp_test_server import definitions_server
from scripted_turn import ScriptedTurn
from app.services.knowledge_evidence import KnowledgeEvidence
from app.tools.knowledge_tools import ALLOWED_TOOL, READ_ACTION, SERVER_NAME


class AgentKnowledgeTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("资源制度", "GPU 申请资料")
        self.other = self.services.knowledge.store.create_base("其他项目", "不应跨库查询")
        self.services.knowledge.ingest(self.base["id"], "gpu.md", "# GPU 申请\n单张 GPU 使用不超过 8 小时，由项目负责人审批。".encode())
        self.services.knowledge.ingest(self.other["id"], "private.md", "# GPU 私有资料\nUNBOUND-SECRET".encode())
        self.runtime = self.services.conversations.runtime

    def definition(self, ids=None):
        return {"name": "知识库助理", "description": "查询绑定的资料", "system_prompt": "使用工具查询资料。",
                "knowledge_base_ids": ids if ids is not None else [self.base["id"]]}

    def create(self):
        response = self.client.post("/api/agents", json=self.definition())
        self.assertEqual(response.status_code, 201, response.text)
        return self.services.registry.get_agent(response.json()["id"])

    def binding_path(self, agent_id):
        return f"/api/agents/{agent_id}/knowledge-bases"

    def bind(self, agent_id, ids):
        return self.client.put(self.binding_path(agent_id), json={"knowledge_base_ids": ids})

    def conversation(self, agent):
        return self.services.store.create(agent.id)

    def tools(self):
        return self.services.deep_agents.tool_services.knowledge

    def test_knowledge_only_agent_creation_survives_restart(self):
        agent = self.create()
        self.assertEqual(agent.tools, [])
        self.assertEqual(agent.knowledge_base_ids, [self.base["id"]])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.get_agent(agent.id), agent)
        bound = self.client.get(self.binding_path(agent.id))
        self.assertEqual(bound.status_code, 200)
        self.assertEqual(bound.json()[0]["id"], self.base["id"])

    def test_existing_builtin_can_replace_and_clear_bindings_without_affecting_others(self):
        agent = self.create()
        self.assertEqual(self.bind("policy_qa_assistant", [self.other["id"]]).status_code, 200)
        self.assertEqual(self.bind("policy_qa_assistant", [self.base["id"]]).status_code, 200)
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.get_agent("policy_qa_assistant").knowledge_base_ids, [self.base["id"]])
        self.assertEqual(self.bind("policy_qa_assistant", []).json(), [])
        self.assertEqual(self.services.registry.get_agent(agent.id).knowledge_base_ids, [self.base["id"]])
        self.assertTrue(self.client.get("/api/agents").json())

    def test_invalid_binding_changes_preserve_previous_configuration(self):
        agent = self.create()
        for ids, status in [([self.other["id"], "missing"], 404), ([self.base["id"]] * 2, 422),
                            ([str(index) for index in range(11)], 422), ([""], 422)]:
            with self.subTest(ids=ids):
                self.assertEqual(self.bind(agent.id, ids).status_code, status)
                self.assertEqual(self.services.registry.get_agent(agent.id).knowledge_base_ids, [self.base["id"]])
        self.assertEqual(self.bind("missing", []).status_code, 404)
        self.assertEqual(self.client.get(self.binding_path("missing")).status_code, 404)

    def test_failed_creation_rolls_back_agent_and_bindings(self):
        response = self.client.post("/api/agents", json=self.definition([self.base["id"], "missing"]))
        self.assertEqual(response.status_code, 404)
        with self.services.store.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM custom_agents").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_knowledge_bases").fetchone()[0], 0)
        for update in [{"knowledge_base_ids": []}, {"knowledge_base_ids": [self.base["id"]] * 2},
                       {"tools": [{"type": "mcp", "name": SERVER_NAME, "url": "http://localhost/mcp", "actions": ["search"]}]}]:
            definition = self.definition()
            definition.update(update)
            self.assertEqual(self.client.post("/api/agents", json=definition).status_code, 422)

    def test_deleting_knowledge_base_cleans_binding_and_unregisters_tool(self):
        agent = self.create()
        self.services.knowledge.delete_base(self.base["id"])
        current = self.services.registry.get_agent(agent.id)
        self.assertEqual(current.knowledge_base_ids, [])
        self.assertEqual(self.client.get(self.binding_path(agent.id)).json(), [])
        turn = self.services.deep_agents.tool_services.prepare("new", current, None, None)
        self.assertNotIn(SERVER_NAME, turn.groups)

    def test_mcp_protocol_exposes_scoped_tool_and_returns_real_sources_and_audit(self):
        agent = self.create()
        conversation_id = self.conversation(agent)
        server = definitions_server(SERVER_NAME, self.tools().definitions(conversation_id, agent))

        async def run():
            async with create_connected_server_and_client_session(server["instance"]) as session:
                tools = (await session.list_tools()).tools
                self.assertEqual([item.name for item in tools], ["search_knowledge", "read_knowledge"])
                self.assertEqual(tools[0].inputSchema["properties"]["knowledge_base_id"]["enum"], [self.base["id"]])
                self.assertIn(self.base["name"], tools[0].description)
                result = await session.call_tool("search_knowledge", {
                    "knowledge_base_id": self.base["id"], "query": "GPU", "limit": 3,
                })
                self.assertFalse(result.isError)
                return json.loads(result.content[0].text)

        result = asyncio.run(run())
        self.assertEqual(result["knowledge_base_id"], self.base["id"])
        self.assertEqual(result["matches"][0]["filename"], "gpu.md")
        self.assertEqual(result["matches"][0]["start_line"], 1)
        self.assertNotIn("UNBOUND-SECRET", json.dumps(result))
        logs = self.services.tool_store.get_audit_logs(conversation_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual((logs[0]["tool_type"], logs[0]["status"]), ("knowledge", "success"))

    def test_tool_rejects_cross_base_access_and_revocation_during_existing_session(self):
        agent = self.create()
        conversation_id = self.conversation(agent)
        for ids, query_id in [(None, self.other["id"]), ([], self.base["id"]),
                              ([self.other["id"]], self.other["id"])]:
            if ids is not None:
                self.assertEqual(self.bind(agent.id, ids).status_code, 200)
            response = self.tools().execute(conversation_id, agent, {"knowledge_base_id": query_id, "query": "GPU"})
            self.assertTrue(response["is_error"])
            self.assertNotIn("UNBOUND-SECRET", json.dumps(response))
        logs = self.services.tool_store.get_audit_logs(conversation_id)
        self.assertEqual([item["status"] for item in logs], ["failed"] * 3)

    def test_read_tool_returns_cited_lines_from_bound_bases_only(self):
        agent = self.create()
        conversation_id = self.conversation(agent)
        evidence = KnowledgeEvidence()
        found = json.loads(self.tools().execute(conversation_id, agent, {"knowledge_base_id": self.base["id"], "query": "GPU"},
                                                evidence)["content"][0]["text"])["matches"][0]
        response = self.tools().execute(conversation_id, agent, {"knowledge_base_id": self.base["id"], "document_id": found["document_id"],
                                                                 "start_line": 2}, evidence, READ_ACTION)
        passage = json.loads(response["content"][0]["text"])
        self.assertEqual((passage["content"], passage["start_line"], passage["end_line"]), ("单张 GPU 使用不超过 8 小时，由项目负责人审批。", 2, 2))
        self.assertTrue(passage["citation_link"].startswith("#source-"))
        citations = evidence.snapshot()[1]["citations"]
        self.assertIn(passage["citation_id"], [item["citation_id"] for item in citations])
        private = self.services.knowledge.store.list_documents(self.other["id"])[0]["id"]
        for arguments in [{"knowledge_base_id": self.other["id"], "document_id": private},
                          {"knowledge_base_id": self.base["id"], "document_id": private},
                          {"knowledge_base_id": self.base["id"], "document_id": found["document_id"], "start_line": 0}]:
            with self.subTest(arguments=arguments):
                failed = self.tools().execute(conversation_id, agent, arguments, None, READ_ACTION)
                self.assertTrue(failed["is_error"])
                self.assertNotIn("UNBOUND-SECRET", json.dumps(failed))
        names = [definition.name for definition in self.tools().definitions(conversation_id, agent)]
        self.assertEqual(names, ["search_knowledge", READ_ACTION])

    def test_tool_handles_empty_matches_invalid_arguments_and_safe_failure(self):
        agent = self.create()
        conversation_id = self.conversation(agent)
        params = {"knowledge_base_id": self.base["id"], "query": "XYZ987NONMATCH"}
        result = self.tools().execute(conversation_id, agent, params)
        self.assertEqual(json.loads(result["content"][0]["text"])["matches"], [])
        for update in [{"query": " "}, {"limit": True}, {"limit": 21}, {"agent_id": "other"}]:
            self.assertTrue(self.tools().execute(conversation_id, agent, {**params, **update})["is_error"])
        with patch.object(self.services.knowledge.__class__, "search", side_effect=RuntimeError("private-db-path")), \
                patch("app.tools.knowledge_tools.logger.exception"):
            result = self.tools().execute(conversation_id, agent, params)
        self.assertTrue(result["is_error"])
        self.assertNotIn("private-db-path", json.dumps(result))

    def test_next_conversation_turn_receives_updated_tool_and_calls_real_index(self):
        agent = self.services.registry.get_agent("policy_qa_assistant")
        conversation_id = self.conversation(agent)
        self.assertEqual(self.bind(agent.id, [self.base["id"]]).status_code, 200)

        model = ScriptedTurn(responses=["unused"], reply="已查到 GPU 申请资料",
                             calls=[(ALLOWED_TOOL, {"knowledge_base_id": self.base["id"], "query": "GPU"})])
        self.services.deep_agents.model_factory = lambda: model
        response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "查询 GPU 申请"})
        self.assertIn("search_knowledge", model.seen[0][0].content)
        self.assertIn("项目负责人", str(model.results[0]))
        self.assertIn('"type": "done"', response.text)
        self.assertNotIn('"type": "error"', response.text)
        logs = self.services.tool_store.get_audit_logs(conversation_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["tool_type"], "knowledge")


if __name__ == "__main__":
    unittest.main()

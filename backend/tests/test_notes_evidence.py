"""真实笔记 MCP 返回值经过共享工具处理、依据事件和历史持久化的集成验证。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.notes_evidence import NotesEvidenceTracker
from mcp_servers.notes_server import create_notes_server
from scripted_turn import ScriptedTurn


class NotesEvidenceTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "notes.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("笔记 · AI", "")
        self.text = "# Transformer\n\nToken → Embedding → 位置编码 → QKV → Attention。"
        self.document = self.services.knowledge.ingest(self.base["id"], "hello.md", self.text.encode())["document"]
        agent = self.client.post("/api/agents", json={
            "name": "笔记助理", "description": "读笔记", "system_prompt": "使用笔记 MCP 回答。",
            "tools": [{"type": "mcp", "name": "my_notes", "transport": "http",
                       "url": "http://localhost:8059/mcp", "actions": ["search_notes", "read_note", "list_notes"]}],
        }).json()
        self.conversation_id = self.services.store.create(agent["id"])
        self.server = create_notes_server(self.settings.database_path)

    @asynccontextmanager
    async def open_session(self, config):
        async with create_connected_server_and_client_session(self.server._mcp_server) as session:
            yield session

    def send(self, *calls, reply="说明本轮结果。"):
        """One turn whose model calls the notes MCP tools in order, then answers (optionally from the results)."""
        model = ScriptedTurn(responses=["unused"], reply=reply, calls=[(f"mcp__my_notes__{action}", params) for action, params in calls])
        self.services.deep_agents.model_factory = lambda: model
        with patch("app.tools.external_tools.open_mcp_session", self.open_session):
            response = self.client.post(f"/api/conversations/{self.conversation_id}/messages/stream", json={"content": "查询笔记"})
        self.model = model
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_mcp_only_agent_search_emits_clickable_snapshot_and_restores_history(self):
        events = self.send(("search_notes", {"query": "Transformer"}),
                           reply=lambda results: f"输入依次处理。[1]({results[0]['collections'][0]['matches'][0]['citation_link']})")
        self.assertIn("citation_link", self.model.seen[0][0].content)
        self.assertEqual(events[-1]["type"], "done")
        evidence = [event["evidence"] for event in events if event["type"] == "knowledge"][-1]
        self.assertEqual(evidence["status"], "matched")
        self.assertIn("notes_mcp", evidence["channels"])
        self.assertEqual(evidence["notes_calls"], 1)
        citation = evidence["citations"][0]
        self.assertEqual(citation["content"], self.text)
        self.assertEqual(citation["source_kind"], "notes_mcp")
        self.assertIn(citation["citation_id"], self.services.store.get_messages(self.conversation_id)[-1]["content"])
        self.services.knowledge.delete_base(self.base["id"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.store.get_messages(self.conversation_id)[-1]["knowledge"], evidence)

    def test_read_without_search_and_partial_failure_keep_source(self):
        self.send(("read_note", {"collection_id": self.base["id"], "note_id": self.document["id"], "offset": 5, "limit": 20}),
                  ("read_note", {"collection_id": self.base["id"], "note_id": "missing"}), reply="部分资料已读取。")
        self.assertTrue(self.model.results[0]["citation_link"].startswith("#source-"))
        evidence = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]
        self.assertEqual(evidence["status"], "matched")
        self.assertEqual(evidence["failed_searches"], 1)
        self.assertEqual(evidence["citations"][0]["content"], self.text[5:25])
        self.assertIsNone(evidence["citations"][0]["chunk_id"])

    def test_listing_empty_search_and_failure_are_distinct(self):
        for action, params, status in [
            ("list_notes", {"collection_id": self.base["id"]}, "not_searched"),
            ("search_notes", {"query": "NOMATCH987"}, "no_match"),
            ("read_note", {"collection_id": self.base["id"], "note_id": "missing"}, "failed"),
        ]:
            self.send((action, params))
            evidence = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]
            self.assertEqual(evidence["status"], status)
            self.assertEqual(evidence["notes_calls"], 1)

    def test_malformed_results_and_other_tools_cannot_add_sources(self):
        evidence = KnowledgeEvidence()
        tracker = NotesEvidenceTracker(evidence, ["my_notes"])
        tracker.capture({"tool_name": "other", "action": "search_notes"}, '{"schema":"workbench.notes.v1"}', False)
        tracker.capture({"tool_name": "my_notes", "action": "search_notes"},
                        '{"schema":"workbench.notes.v0","evidence":{"status":"matched","citations":[]}}', False)
        tracker.capture({"tool_name": "my_notes", "action": "search_notes"}, [{"type": "text", "text": "not json"}], False)
        snapshot = evidence.snapshot()[1]
        self.assertEqual(snapshot["citations"], [])
        self.assertEqual(snapshot["notes_calls"], 2)
        self.assertEqual(snapshot["failed_searches"], 2)


if __name__ == "__main__":
    unittest.main()

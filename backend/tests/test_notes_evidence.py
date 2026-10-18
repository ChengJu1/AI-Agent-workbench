"""真实笔记 MCP 返回值经过 SDK 消息、依据事件和历史持久化的集成验证。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, StreamEvent, ToolResultBlock, ToolUseBlock, UserMessage
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from mcp_servers.notes_server import create_notes_server


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

    async def tool_messages(self, action, params, call_id="call-1"):
        yield AssistantMessage(content=[ToolUseBlock(id=call_id, name=f"mcp__my_notes__{action}", input=params)], model="test")
        async with create_connected_server_and_client_session(self.server._mcp_server) as session:
            result = await session.call_tool(action, params)
            self.result = json.loads(result.content[0].text) if not result.isError else None
            yield UserMessage(content=[ToolResultBlock(tool_use_id=call_id,
                content=[{"type": "text", "text": item.text} for item in result.content], is_error=result.isError)])

    def delta(self, text):
        return StreamEvent(uuid="delta", session_id=self.conversation_id,
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})

    def send(self, query):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            response = self.client.post(f"/api/conversations/{self.conversation_id}/messages/stream", json={"content": "查询笔记"})
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_mcp_only_agent_search_emits_clickable_snapshot_and_restores_history(self):
        async def query(prompt, options):
            async for message in self.tool_messages("search_notes", {"query": "Transformer"}):
                yield message
            self.assertIn("citation_link", options.system_prompt)
            link = self.result["collections"][0]["matches"][0]["citation_link"]
            yield self.delta(f"输入依次处理。[1]({link})")
        events = self.send(query)
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
        async def query(prompt, options):
            async for message in self.tool_messages("read_note", {"collection_id": self.base["id"], "note_id": self.document["id"], "offset": 5, "limit": 20}):
                yield message
            self.assertTrue(self.result["citation_link"].startswith("#source-"))
            async for message in self.tool_messages("read_note", {"collection_id": self.base["id"], "note_id": "missing"}, "call-2"):
                yield message
            yield self.delta("部分资料已读取。")
        self.send(query)
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
            async def query(prompt, options):
                async for message in self.tool_messages(action, params):
                    yield message
                yield self.delta("说明本轮结果。")
            self.send(query)
            evidence = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]
            self.assertEqual(evidence["status"], status)
            self.assertEqual(evidence["notes_calls"], 1)

    def test_malformed_and_unrequested_tool_results_cannot_add_sources(self):
        async def query(prompt, options):
            yield UserMessage(content=[ToolResultBlock(tool_use_id="unrequested", content='{"schema":"workbench.notes.v1"}')])
            yield AssistantMessage(content=[ToolUseBlock(id="bad", name="mcp__my_notes__search_notes", input={"query": "x"})], model="test")
            yield UserMessage(content=[ToolResultBlock(tool_use_id="bad", content='{"schema":"workbench.notes.v1","evidence":{"status":"matched","citations":[]}}')])
            yield self.delta("无可核验资料。")
        self.send(query)
        evidence = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]
        self.assertEqual(evidence["citations"], [])
        self.assertEqual(evidence["status"], "failed")

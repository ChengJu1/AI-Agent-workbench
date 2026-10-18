"""验证引用来自实际工具结果，按轮次隔离，并在更新、断流和重启后保留。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import StreamEvent
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.knowledge_evidence import KnowledgeEvidence
from app.tools.knowledge_tools import SERVER_NAME


class AnswerEvidenceTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("GPU 申请制度", "演示")
        self.original = "# GPU 申请\n申请两张 GPU，需要项目负责人和资源管理员共同审批。"
        self.services.knowledge.ingest(self.base["id"], "gpu.md", self.original.encode())
        created = self.client.post("/api/agents", json={
            "name": "资料助理", "description": "查资料", "system_prompt": "检索并引用资料。",
            "knowledge_base_ids": [self.base["id"]],
        })
        self.agent = self.services.registry.get_agent(created.json()["id"])
        self.conversation_id = self.services.store.create(self.agent.id)
        self.result = None

    def delta(self, text):
        return StreamEvent(uuid="delta", session_id=self.conversation_id, event={
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": text},
        })

    async def retrieve(self, options, query="GPU"):
        async with create_connected_server_and_client_session(options.mcp_servers[SERVER_NAME]["instance"]) as session:
            result = await session.call_tool("search_knowledge", {"knowledge_base_id": self.base["id"], "query": query})
            self.assertFalse(result.isError)
            self.result = json.loads(result.content[0].text)
            return self.result

    def send(self, query):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            response = self.client.post(f"/api/conversations/{self.conversation_id}/messages/stream", json={"content": "请查询制度"})
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_live_evidence_and_history_have_matching_snapshot_and_citation_link(self):
        async def query(prompt, options):
            result = await self.retrieve(options)
            self.assertIn("不得编造引用", options.system_prompt)
            link = result["matches"][0]["citation_link"]
            yield self.delta(f"需要共同审批。[1]({link})")

        events = self.send(query)
        evidence = [event["evidence"] for event in events if event["type"] == "knowledge"][-1]
        self.assertEqual(evidence["status"], "matched")
        citation = evidence["citations"][0]
        self.assertEqual(citation["content"], self.original)
        self.assertEqual(citation["citation_id"], self.result["matches"][0]["citation_id"])
        self.assertEqual((citation["filename"], citation["document_version"], citation["start_line"], citation["end_line"]),
                         ("gpu.md", 1, 1, 2))
        self.assertEqual(events[-1]["type"], "done")
        history = self.client.get(f"/api/conversations/{self.conversation_id}/messages").json()
        self.assertEqual(history[-1]["knowledge"], evidence)
        self.assertEqual(history[-1]["status"], "complete")
        self.services.knowledge.ingest(self.base["id"], "gpu.md", b"# GPU\nChanged policy")
        self.services.knowledge.delete_base(self.base["id"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.store.get_messages(self.conversation_id)[-1], history[-1])
        self.assertEqual(fresh.store.get_messages(self.conversation_id)[-1]["knowledge"]["citations"][0]["content"], self.original)

    def test_empty_results_and_skipped_search_have_distinct_states(self):
        async def no_match(prompt, options):
            await self.retrieve(options, "NONMATCH987")
            yield self.delta("没有找到相关资料，无法确认具体制度。")

        events = self.send(no_match)
        evidence = next(event["evidence"] for event in events if event["type"] == "knowledge")
        self.assertEqual(evidence["status"], "no_match")
        self.assertEqual(evidence["citations"], [])

        async def skipped(prompt, options):
            yield self.delta("你好，请说明需要查询的资料。")

        events = self.send(skipped)
        evidence = next(event["evidence"] for event in events if event["type"] == "knowledge")
        self.assertEqual(evidence["status"], "not_searched")
        self.assertEqual(evidence["queries"], [])

    def test_merged_retrieval_reaches_sdk_tool_and_persists_exact_source_snapshot(self):
        text = "# 总则\n资源制度。\n\n## GPU\n申请需要共同审批。\n\n## 附则\n特殊情况另行确认。"
        self.services.knowledge.ingest(self.base["id"], "gpu.md", text.encode())

        async def query(prompt, options):
            result = await self.retrieve(options)
            self.assertEqual(result["diagnostics"]["candidate_count"], 2)
            self.assertEqual(result["diagnostics"]["unique_count"], 1)
            self.assertGreaterEqual(result["diagnostics"]["elapsed_ms"], result["diagnostics"]["deduplication_ms"])
            self.assertEqual(len(result["matches"]), 1)
            self.assertEqual(len(result["matches"][0]["source_chunk_ids"]), 2)
            self.assertEqual(result["matches"][0]["content"], text)
            yield self.delta(f"需要共同审批。[1]({result['matches'][0]['citation_link']})")

        events = self.send(query)
        self.assertEqual(events[-1]["type"], "done")
        citation = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]["citations"][0]
        self.assertEqual(citation["content"], text)
        self.assertEqual(citation["document_version"], 2)
        self.assertEqual((citation["start_line"], citation["end_line"]), (1, 8))

    def test_citation_identifiers_are_not_reused_in_followup_turns(self):
        async def query(prompt, options):
            result = await self.retrieve(options)
            yield self.delta(f"依据资料。[1]({result['matches'][0]['citation_link']})")

        self.send(query)
        self.send(query)
        answers = [message for message in self.services.store.get_messages(self.conversation_id) if message["role"] == "assistant"]
        first = answers[0]["knowledge"]["citations"][0]["citation_id"]
        second = answers[1]["knowledge"]["citations"][0]["citation_id"]
        self.assertNotEqual(first, second)
        self.assertIn(first, answers[0]["content"])
        self.assertIn(second, answers[1]["content"])

    def test_tool_result_survives_model_failure_before_any_text(self):
        async def query(prompt, options):
            await self.retrieve(options)
            if False:
                yield self.delta("")
            raise RuntimeError("private-model-details")

        with patch("app.services.conversation_service.logger.exception"):
            events = self.send(query)
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("private-model-details", json.dumps(events))
        answer = self.services.store.get_messages(self.conversation_id)[-1]
        self.assertEqual(answer["content"], "")
        self.assertEqual(answer["status"], "failed")
        self.assertEqual(answer["knowledge"]["citations"][0]["content"], self.original)

    def test_disconnect_preserves_snapshot_and_marks_incomplete_answer(self):
        closed = []

        async def query(prompt, options):
            try:
                await self.retrieve(options)
                yield self.delta("部分回答")
            finally:
                closed.append(True)

        async def run():
            service = self.services.conversations
            prepared = service.prepare(self.conversation_id, "查询资料")
            stream = service.stream(self.conversation_id, "查询资料", prepared)
            self.assertEqual((await anext(stream))["type"], "knowledge")
            await stream.aclose()
            self.assertEqual(closed, [True])
            self.assertNotIn(self.conversation_id, service._active)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            asyncio.run(run())
        answer = self.services.store.get_messages(self.conversation_id)[-1]
        self.assertEqual(answer["status"], "failed")
        self.assertEqual(answer["knowledge"]["status"], "matched")

    def test_failed_tool_is_reported_separately_from_empty_search(self):
        evidence = KnowledgeEvidence()
        tools = self.services.conversations.runtime._knowledge_tools
        response = tools.execute(self.conversation_id, self.agent, {"knowledge_base_id": "not-bound", "query": "GPU"}, evidence)
        self.assertTrue(response["is_error"])
        snapshot = evidence.snapshot()[1]
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["failed_searches"], 1)
        self.assertEqual(snapshot["citations"], [])

    def test_parallel_repeated_searches_deduplicate_sources_but_keep_versions(self):
        result = self.services.knowledge.search(self.base["id"], "GPU", 5)
        result.update(knowledge_base_id=self.base["id"], knowledge_base_name=self.base["name"])
        evidence = KnowledgeEvidence()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(evidence.record, [result] * 8))
        ids = {item["matches"][0]["citation_id"] for item in results}
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(evidence.snapshot()[1]["citations"]), 1)
        self.services.knowledge.ingest(self.base["id"], "gpu.md", b"# GPU\nUpdated rules")
        updated = self.services.knowledge.search(self.base["id"], "GPU", 5)
        updated.update(knowledge_base_id=self.base["id"], knowledge_base_name=self.base["name"])
        evidence.record(updated)
        self.assertEqual([item["document_version"] for item in evidence.snapshot()[1]["citations"]], [1, 2])

    def test_message_metadata_migration_preserves_legacy_history_and_is_idempotent(self):
        store = self.services.store
        store.add_message(self.conversation_id, "user", "旧消息")
        with store.database.connection() as connection:
            connection.execute("ALTER TABLE messages DROP COLUMN metadata")
        store.database.initialize()
        store.database.initialize()
        self.assertEqual(store.get_messages(self.conversation_id), [{"role": "user", "content": "旧消息"}])


if __name__ == "__main__":
    unittest.main()

"""验证引用来自实际工具结果，按轮次隔离，并在更新、断流和重启后保留。"""
import asyncio
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.knowledge_evidence import KnowledgeEvidence
from app.tools.knowledge_tools import SERVER_NAME
from scripted_turn import ScriptedTurn


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

    def search(self, reply, query="GPU", **kwargs):
        """A model that searches the bound knowledge base once, then answers from the real result."""
        return ScriptedTurn(responses=["unused"], reply=reply, **kwargs, calls=[
            (f"mcp__{SERVER_NAME}__search_knowledge", {"knowledge_base_id": self.base["id"], "query": query})])

    def send(self, model):
        self.services.deep_agents.model_factory = lambda: model
        response = self.client.post(f"/api/conversations/{self.conversation_id}/messages/stream", json={"content": "请查询制度"})
        if model.results:
            self.result = model.results[0]
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_live_evidence_and_history_have_matching_snapshot_and_citation_link(self):
        model = self.search(lambda results: f"需要共同审批。[1]({results[0]['matches'][0]['citation_link']})")
        events = self.send(model)
        self.assertIn("不得编造引用", model.seen[0][0].content)
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
        events = self.send(self.search("没有找到相关资料，无法确认具体制度。", query="NONMATCH987"))
        evidence = next(event["evidence"] for event in events if event["type"] == "knowledge")
        self.assertEqual(evidence["status"], "no_match")
        self.assertEqual(evidence["citations"], [])

        events = self.send(ScriptedTurn(responses=["unused"], reply="你好，请说明需要查询的资料。"))
        evidence = next(event["evidence"] for event in events if event["type"] == "knowledge")
        self.assertEqual(evidence["status"], "not_searched")
        self.assertEqual(evidence["queries"], [])

    def test_merged_retrieval_reaches_the_tool_and_persists_exact_source_snapshot(self):
        text = "# 总则\n资源制度。\n\n## GPU\n申请需要共同审批。\n\n## 附则\n特殊情况另行确认。"
        self.services.knowledge.ingest(self.base["id"], "gpu.md", text.encode())

        events = self.send(self.search(lambda results: f"需要共同审批。[1]({results[0]['matches'][0]['citation_link']})"))
        result = self.result
        self.assertEqual(result["diagnostics"]["candidate_count"], 2)
        self.assertEqual(result["diagnostics"]["unique_count"], 1)
        self.assertGreaterEqual(result["diagnostics"]["elapsed_ms"], result["diagnostics"]["deduplication_ms"])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(len(result["matches"][0]["source_chunk_ids"]), 2)
        self.assertEqual(result["matches"][0]["content"], text)
        self.assertEqual(events[-1]["type"], "done")
        citation = self.services.store.get_messages(self.conversation_id)[-1]["knowledge"]["citations"][0]
        self.assertEqual(citation["content"], text)
        self.assertEqual(citation["document_version"], 2)
        self.assertEqual((citation["start_line"], citation["end_line"]), (1, 8))

    def test_citation_identifiers_are_not_reused_in_followup_turns(self):
        reply = lambda results: f"依据资料。[1]({results[0]['matches'][0]['citation_link']})"
        self.send(self.search(reply))
        self.send(self.search(reply))
        answers = [message for message in self.services.store.get_messages(self.conversation_id) if message["role"] == "assistant"]
        first = answers[0]["knowledge"]["citations"][0]["citation_id"]
        second = answers[1]["knowledge"]["citations"][0]["citation_id"]
        self.assertNotEqual(first, second)
        self.assertIn(first, answers[0]["content"])
        self.assertIn(second, answers[1]["content"])

    def test_tool_result_survives_model_failure_before_any_text(self):
        with patch("app.runtime.deep_agents.logger.exception"):
            events = self.send(self.search("", fail_after_tools=True))
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("private-model-details", json.dumps(events))
        answer = self.services.store.get_messages(self.conversation_id)[-1]
        self.assertEqual(answer["content"], "")
        self.assertEqual(answer["status"], "failed")
        self.assertEqual(answer["knowledge"]["citations"][0]["content"], self.original)

    def test_disconnect_preserves_snapshot_and_marks_incomplete_answer(self):
        self.services.deep_agents.model_factory = lambda: self.search("部分回答")

        async def run():
            service = self.services.conversations
            prepared = service.prepare(self.conversation_id, "查询资料")
            stream = service.stream(self.conversation_id, "查询资料", prepared)
            try:
                event = await anext(stream)
                while event['type'] in ('tool_started', 'tool_finished'):
                    event = await anext(stream)
                self.assertEqual(event['type'], 'knowledge')
            finally:
                await stream.aclose()
            self.assertNotIn(self.conversation_id, service._active)

        asyncio.run(run())
        answer = self.services.store.get_messages(self.conversation_id)[-1]
        self.assertEqual(answer["status"], "failed")
        self.assertEqual(answer["knowledge"]["status"], "matched")

    def test_failed_tool_is_reported_separately_from_empty_search(self):
        evidence = KnowledgeEvidence()
        tools = self.services.deep_agents.tool_services.knowledge
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

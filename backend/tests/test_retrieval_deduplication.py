"""重叠来源只返回一次，排序、来源快照和计时反馈须保持可信。"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.models.evaluation import RetrievalSuite
from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.retrieval_postprocessing import deduplicate_matches


def source(text, start, end, chunk_id, document="doc", version=1):
    return {"id": chunk_id, "document_id": document, "document_version": version,
            "filename": document + ".md", "ordinal": chunk_id, "section": f"章节 {chunk_id}",
            "content": text[start:end], "start_offset": start, "end_offset": end,
            "start_line": text[:start].count("\n") + 1, "end_line": text[:end - 1].count("\n") + 1}


class OverlapMergeTestCase(unittest.TestCase):
    def test_overlapping_ranges_merge_exact_original_in_source_order_and_keep_best_rank(self):
        text = "# A\n说明✅\n\n# B\nGPU 审批\n\n# C\n补充规则"
        b, c = text.index("# B"), text.index("# C")
        # B+C 排在 A+B 前面；合并后的原文仍应从 A 开始，代表 id 仍取排名最佳项。
        candidates = [source(text, b, len(text), 2), source("other", 0, 5, 9, "other"),
                      source(text, 0, c - 2, 1)]
        original = copy.deepcopy(candidates)
        groups, skipped = deduplicate_matches(candidates)
        self.assertEqual(skipped, 0)
        self.assertEqual([g["id"] for g in groups], [2, 9])
        self.assertEqual(groups[0]["content"], text)
        self.assertEqual(groups[0]["source_chunk_ids"], [1, 2])
        self.assertEqual((groups[0]["start_offset"], groups[0]["end_offset"]), (0, len(text)))
        self.assertEqual(groups[0]["end_line"], text.count("\n") + 1)
        self.assertEqual(candidates, original)

    def test_bridge_and_contained_matches_merge_without_duplicating_text(self):
        text = "0123456789abcdefghijklmnopqrstuvwxyz"
        candidates = [source(text, 0, 10, 1), source(text, 20, 30, 2),
                      source(text, 8, 23, 3), source(text, 3, 6, 4), source(text, 0, 10, 1)]
        groups, _ = deduplicate_matches(candidates)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["content"], text[:30])
        self.assertEqual(groups[0]["source_chunk_ids"], [1, 2, 3, 4])

    def test_same_text_in_different_documents_versions_or_nonoverlapping_positions_is_preserved(self):
        text = "same same"
        candidates = [source(text, 0, 4, 1), source(text, 5, 9, 2),
                      source(text, 0, 4, 3, document="another"), source(text, 0, 4, 4, version=2)]
        groups, _ = deduplicate_matches(candidates)
        self.assertEqual(len(groups), 4)
        # 相邻但没有交集的来源也不拼接，避免人为补入未检索的间隙。
        adjacent, _ = deduplicate_matches([source(text, 0, 4, 1), source(text, 4, 9, 2)])
        self.assertEqual(len(adjacent), 2)

    def test_merge_cap_preserves_best_match_and_does_not_return_overlapping_tail(self):
        text = "0123456789abcdefghijklmnopqrstuvwxyz"
        groups, skipped = deduplicate_matches([source(text, 0, 15, 1), source(text, 10, 30, 2),
                                               source(text, 31, 36, 3)], max_characters=20)
        self.assertEqual(skipped, 1)
        self.assertEqual([g["id"] for g in groups], [1, 3])
        self.assertEqual(groups[0]["content"], text[:15])
        # 已有原片段本身超过上限时不截断；只阻止合并继续扩展。
        long_groups, _ = deduplicate_matches([source(text, 0, 30, 1), source(text, 20, 36, 2)], max_characters=20)
        self.assertEqual(long_groups[0]["content"], text[:30])
        self.assertEqual(len(long_groups), 1)


class DeduplicatedRetrievalTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.services = build_services(Settings(database_path=Path(directory.name) / "test.db"))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("去重验证", "")
        self.text = "# A\n申请条件\n\n## B\nalpha 审批。✅\n\n## C\n特别说明"
        self.document = self.services.knowledge.ingest(self.base["id"], "policy.md", self.text.encode())["document"]

    def search(self, query="alpha", limit=5):
        response = self.client.post(f"/api/knowledge-bases/{self.base['id']}/search", json={"query": query, "limit": limit})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_api_merges_overlapping_hits_and_reports_timing_even_for_empty_results(self):
        result = self.search()
        self.assertEqual(result["diagnostics"]["candidate_count"], 2)
        self.assertEqual(result["diagnostics"]["unique_count"], 1)
        self.assertEqual(len(result["matches"]), 1)
        match = result["matches"][0]
        self.assertEqual(match["content"], self.text)
        self.assertEqual(len(match["source_chunk_ids"]), 2)
        self.assertEqual(self.text[match["start_offset"]:match["end_offset"]], match["content"])
        for query in ("missingxyz", "💡"):
            empty = self.search(query)
            self.assertEqual(empty["matches"], [])
            self.assertEqual(empty["diagnostics"]["candidate_count"], 0)
            self.assertEqual(empty["diagnostics"]["unique_count"], 0)
            self.assertGreaterEqual(empty["diagnostics"]["elapsed_ms"], empty["diagnostics"]["deduplication_ms"])

    def test_candidate_overfetch_fills_result_slots_after_dedup_and_preserves_ranking(self):
        store = self.services.knowledge.store
        text = "abcdefghij"
        candidates = [source(text, 0, 6, 1), source(text, 4, 10, 2), source("other", 0, 5, 3, "other")]
        with patch.object(store, "_search", return_value=candidates) as retrieval:
            result = self.services.knowledge.search(self.base["id"], "alpha", 2)
        self.assertEqual(retrieval.call_args.args[-1], 6)
        self.assertEqual([g["id"] for g in result["matches"]], [1, 3])
        self.assertEqual(result["diagnostics"]["candidate_count"], 3)
        self.assertEqual(result["diagnostics"]["unique_count"], 2)

    def test_timing_uses_monotonic_clock_and_includes_deduplication(self):
        with patch("app.storage.knowledge_store.perf_counter", side_effect=[10.0, 10.01, 10.012]):
            result = self.services.knowledge.search(self.base["id"], "alpha", 5)
        self.assertEqual(result["diagnostics"]["elapsed_ms"], 12.0)
        self.assertEqual(result["diagnostics"]["deduplication_ms"], 2.0)

    def test_evaluation_uses_same_merged_sources_and_exports_each_query_timing(self):
        suite = RetrievalSuite.model_validate({"name": "去重测试", "cases": [
            {"id": "merged", "query": "alpha", "expected_filename": "policy.md", "expected_texts": ["申请条件", "特别说明"]},
            {"id": "empty", "query": "missingxyz", "expect_no_match": True},
        ]})
        response = self.client.post(f"/api/knowledge-evaluations/{self.base['id']}/run", json=suite.model_dump())
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertEqual(report["results"][0]["matches"], self.search()["matches"])
        self.assertTrue(report["results"][0]["source_positions_valid"])
        self.assertEqual(report["results"][0]["diagnostics"]["candidate_count"], 2)
        self.assertEqual(report["retrieval_policy"], "overlap_merge_v1")
        self.assertGreaterEqual(report["elapsed_ms"], 0)
        expected_average = round(sum(row["diagnostics"]["elapsed_ms"] for row in report["results"]) / 2, 3)
        self.assertEqual(report["average_retrieval_ms"], expected_average)

    def test_representative_chunk_does_not_reuse_citation_id_for_a_different_merged_range(self):
        result = self.services.knowledge.search(self.base["id"], "alpha", 5)
        result.update(knowledge_base_id=self.base["id"], knowledge_base_name=self.base["name"])
        evidence = KnowledgeEvidence()
        full = evidence.record(result)
        shorter = copy.deepcopy(result)
        match = shorter["matches"][0]
        match["start_offset"] = self.text.index("## B")
        match["start_line"] = self.text[:match["start_offset"]].count("\n") + 1
        match["content"] = self.text[match["start_offset"]:]
        narrowed = evidence.record(shorter)
        self.assertNotEqual(full["matches"][0]["citation_id"], narrowed["matches"][0]["citation_id"])
        self.assertEqual(evidence.snapshot()[1]["citations"][0]["content"], self.text)
        again = evidence.record(result)
        self.assertEqual(full["matches"][0]["citation_id"], again["matches"][0]["citation_id"])


if __name__ == "__main__":
    unittest.main()

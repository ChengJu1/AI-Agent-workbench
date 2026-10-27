"""关键词与向量两路按名次融合；模型缺失时退回关键词，向量随片段增删保持一致。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.evaluation import RetrievalSuite
from app.services.embeddings import EmbeddingUnavailable, LocalEmbedder
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_evaluation import RetrievalEvaluationService
from app.services.retrieval_postprocessing import fuse_rankings
from app.storage.database import Database
from app.storage.knowledge_store import KnowledgeStore


# 每组同义词占一个维度：文本含该组任一词时该维为 1。
CONCEPTS = [("断开", "关闭连接", "close"), ("报销", "费用"), ("GPU", "显卡")]


class FakeEmbedder:
    def __init__(self, model_name="fake-model", available=True):
        self.model_name, self.ready, self.passage_calls = model_name, available, 0

    def available(self):
        return self.ready

    def _vector(self, text):
        vector = np.array([float(any(word in text for word in group)) for group in CONCEPTS] + [0.01], dtype=np.float32)
        return vector / np.linalg.norm(vector)

    def passages(self, texts):
        if not self.ready:
            raise EmbeddingUnavailable("missing")
        self.passage_calls += 1
        return np.stack([self._vector(text) for text in texts])

    def query(self, text):
        if not self.ready:
            raise EmbeddingUnavailable("missing")
        return self._vector(text)


class FakeReranker:
    """只认“断开/关闭连接”这一组概念：查询和原文都含该组的词给 0.9，否则 0.01。"""
    model_name = "fake-reranker"

    def __init__(self):
        self.ready = True

    def available(self):
        return self.ready

    def scores(self, query, texts):
        asked = any(word in query for word in CONCEPTS[0])
        return [0.9 if asked and any(word in text for word in CONCEPTS[0]) else 0.01 for text in texts]


class HybridRetrievalTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        database = Database(self.directory / "test.db")
        database.initialize()
        self.store = KnowledgeStore(database)
        self.embedder = FakeEmbedder()
        self.knowledge = KnowledgeService(self.store, self.embedder)
        self.knowledge.schedule_vectors = lambda: None  # 测试里同步调用 index_vectors。
        self.base_id = self.store.create_base("笔记", "")["id"]
        self.knowledge.ingest(self.base_id, "network.md", "# 网络\n\n用完之后要关闭连接，释放资源。".encode())
        self.knowledge.ingest(self.base_id, "finance.md", "# 财务\n\n差旅费用凭发票报销。".encode())

    def vector_count(self):
        with self.store.database.connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM knowledge_chunk_vectors").fetchone()[0]

    def test_rrf_orders_by_rank_and_records_each_channel(self):
        keyword = [{"id": 0, "keyword_score": 9.5}, {"id": 1, "keyword_score": 3.25}]
        vector = [{"id": 1, "similarity": 0.91}, {"id": 2, "similarity": 0.8}]
        fused = fuse_rankings(keyword, vector)
        self.assertEqual([row["id"] for row in fused], [1, 0, 2])
        self.assertEqual(fused[0]["ranking"], {"keyword_rank": 2, "keyword_score": 3.25, "vector_rank": 1,
                                               "similarity": 0.91, "rrf_score": round(1 / 62 + 1 / 61, 6)})
        self.assertNotIn("similarity", fused[0])
        self.assertEqual(fused[2]["ranking"]["keyword_rank"], None)

    def test_reranker_flags_low_relevance_without_hiding_or_reordering_results(self):
        self.knowledge.index_vectors()
        self.knowledge.reranker = FakeReranker()
        relevant = self.knowledge.search(self.base_id, "怎么断开", 5)
        self.assertEqual(relevant["matches"][0]["ranking"]["rerank_score"], 0.9)
        self.assertEqual((relevant["diagnostics"]["low_relevance"], relevant["notice"]), (False, None))
        # 相关度低：结果照常返回、顺序不变，只附上提示，由 Agent 核对。
        unrelated = self.knowledge.search(self.base_id, "差旅报销", 5)
        self.assertEqual(unrelated["matches"][0]["filename"], "finance.md")
        self.assertEqual((unrelated["diagnostics"]["low_relevance"], unrelated["diagnostics"]["relevance_score"]), (True, 0.01))
        self.assertIn("相关度很低", unrelated["notice"])
        self.knowledge.reranker.ready = False
        fallback = self.knowledge.search(self.base_id, "费用", 5)
        self.assertEqual((fallback["diagnostics"]["rerank_status"], fallback["diagnostics"]["low_relevance"], fallback["notice"]),
                         ("unavailable", None, None))

    def test_evaluation_counts_flagged_negative_as_correct(self):
        self.knowledge.index_vectors()
        self.knowledge.reranker = FakeReranker()
        suite = RetrievalSuite.model_validate({"name": "负例", "limit": 3, "cases": [
            {"id": "n1", "query": "差旅报销", "category": "negative", "expect_no_match": True}]})
        report = RetrievalEvaluationService(self.store, self.knowledge).run(self.base_id, suite)
        self.assertEqual((report["summary"]["negative_correct"], report["rerank_model"]), (1, "fake-reranker"))
        self.assertIn("可能不相关", report["results"][0]["reason"])

    def test_vectors_find_paraphrase_that_keywords_miss(self):
        self.assertEqual(self.knowledge.search(self.base_id, "怎么断开", 5)["matches"], [])  # 没有向量时只靠关键词
        self.assertEqual(self.knowledge.index_vectors(), 2)
        self.assertEqual(self.knowledge.index_vectors(), 0)
        result = self.knowledge.search(self.base_id, "怎么断开", 5)
        self.assertEqual(result["method"], "hybrid")
        self.assertEqual(result["matches"][0]["filename"], "network.md")
        diagnostics = result["diagnostics"]
        self.assertEqual((diagnostics["keyword_candidates"], diagnostics["vector_coverage"]), (0, 1.0))
        self.assertEqual(diagnostics["vector_status"], "ok")

    def test_missing_model_falls_back_to_keyword_search(self):
        self.embedder.ready = False
        self.assertEqual(self.knowledge.index_vectors(), 0)
        result = self.knowledge.search(self.base_id, "报销", 5)
        self.assertEqual((result["method"], result["diagnostics"]["vector_status"]), ("keyword", "unavailable"))
        self.assertEqual(result["matches"][0]["filename"], "finance.md")
        self.assertEqual(KnowledgeService(self.store).search(self.base_id, "报销", 5)["diagnostics"]["vector_status"],
                         "disabled")

    def test_vectors_follow_chunk_replacement_deletion_and_model_change(self):
        self.knowledge.index_vectors()
        stale = self.store.chunks_without_vectors("fake-model", 10)
        self.assertEqual(stale, [])
        with self.store.database.connection() as connection:
            old_ids = [row[0] for row in connection.execute("SELECT id FROM knowledge_chunks")]
        self.knowledge.ingest(self.base_id, "network.md", "# 网络\n\n记得 close 连接。".encode())
        self.assertEqual(self.vector_count(), 1)  # 被替换的片段连同向量一起删除
        # 生成期间被删除的片段不应写入向量。
        self.store.save_vectors("fake-model", old_ids, self.embedder.passages(["x"] * len(old_ids)))
        self.assertEqual(self.vector_count(), 1)
        other = KnowledgeService(self.store, FakeEmbedder("other-model"))
        self.assertEqual(other.index_vectors(), 2)  # 换模型后旧向量作废，全部重建
        with self.store.database.connection() as connection:
            self.assertEqual({row[0] for row in connection.execute("SELECT model FROM knowledge_chunk_vectors")},
                             {"other-model"})

    def test_evaluation_reports_hybrid_method_and_model(self):
        self.knowledge.index_vectors()
        suite = RetrievalSuite.model_validate({
            "name": "混合", "limit": 3,
            "cases": [{"id": "c1", "query": "怎么断开", "category": "paraphrase", "expected_filename": "network.md", "expected_texts": ["关闭连接"]}],
        })
        evaluation = RetrievalEvaluationService(self.store, self.knowledge)
        report = evaluation.run(self.base_id, suite)
        self.assertEqual((report["method"], report["embedding_model"]), ("hybrid_rrf", "fake-model"))
        self.assertEqual(report["summary"]["top1_hits"], 1)
        keyword = evaluation.run(self.base_id, suite, hybrid=False)
        self.assertEqual((keyword["method"], keyword["summary"]["top1_hits"]), ("keyword_bm25", 0))

    def test_local_embedder_never_creates_or_downloads_into_missing_directory(self):
        embedder = LocalEmbedder("intfloat/multilingual-e5-large", self.directory / "models")
        self.assertFalse(embedder.available())
        self.assertFalse((self.directory / "models").exists())
        with self.assertRaises(EmbeddingUnavailable):
            embedder.query("测试")


if __name__ == "__main__":
    unittest.main()

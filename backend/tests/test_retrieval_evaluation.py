"""用真实索引验证评估分母、失败题、快照一致性和知识库范围。"""
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
from app.services.retrieval_evaluation import sample_suite


class RetrievalEvaluationTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.services = build_services(Settings(database_path=Path(directory.name) / "test.db"))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("评估验证", "测试")
        self.path = f"/api/knowledge-evaluations/{self.base['id']}/run"

    def positive(self, case_id="positive", query="alpha", filename="policy.md", expected="alpha"):
        return {"id": case_id, "query": query, "expected_filename": filename, "expected_texts": [expected]}

    def negative(self, case_id="negative", query="missingxyz"):
        return {"id": case_id, "query": query, "expect_no_match": True}

    def run_suite(self, cases, limit=5):
        response = self.client.post(self.path, json={"name": "验证题集", "limit": limit, "cases": cases})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_sample_suite_keeps_synonym_challenge_and_real_failure(self):
        # 测试夹具留在后端构建上下文内，容器测试无需读取宿主机 docs。
        documents = {
            "01-资源申请制度.md": "# GPU 申请制度\n项目负责人和资源管理员共同审批。提前 1 个工作日。100 GB，14 天。超过 30 分钟没有有效任务时释放。",
            "02-工时填报规范.md": "# 工时填报\n每周五 18:00 前提交。最小单位 0.5 小时。更正申请填写修改后时长、更正原因。提交周报不等于提交工时。",
            "03-产品说明与常见问题.md": "# 邀请链接\n有效期 72 小时。申请提交后进入待审核状态。",
            "04-值班排障操作手册.md": "# 操作手册\nKB-UPLOAD-01 检查文件格式、文件大小和文本编码。KB-SEARCH-02 检查唯一编号。MCP-CONNECT-03 确认服务配置是否填写完整。故障超过 30 分钟时升级。",
        }
        for filename, content in documents.items():
            self.services.knowledge.ingest(self.base["id"], filename, content.encode())
        suite = self.client.get("/api/knowledge-evaluations/sample-suite")
        self.assertEqual(suite.status_code, 200)
        self.assertEqual(suite.json(), sample_suite().model_dump())
        response = self.client.post(self.path, json=suite.json())
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        rows = {row["case"]["id"]: row for row in report["results"]}
        self.assertEqual(report["summary"]["total"], 18)
        self.assertEqual(report["summary"]["not_applicable"], 0)
        self.assertEqual(rows["gpu-approval"]["status"], "passed")
        self.assertEqual(rows["gpu-synonym"]["status"], "failed")
        self.assertEqual(rows["missing-code"]["status"], "passed")
        self.assertEqual(len(report["documents"]), 4)

    def test_metrics_use_correct_denominators_and_do_not_count_missing_docs_as_passes(self):
        self.services.knowledge.ingest(self.base["id"], "policy.md", b"alpha approval")
        report = self.run_suite([
            self.positive(), self.positive("miss", "omega"), self.negative(),
            self.negative("false-positive", "alpha"), self.positive("missing-doc", filename="absent.md"),
        ])
        self.assertEqual(report["summary"], {
            "total": 5, "evaluated": 4, "passed": 2, "failed": 2, "not_applicable": 1,
            "positive_evaluated": 2, "top1_hits": 1, "top_k_hits": 1, "negative_evaluated": 2,
            "negative_correct": 1, "pass_rate": 0.5, "top1_hit_rate": 0.5,
            "top_k_hit_rate": 0.5, "negative_accuracy": 0.5,
        })
        self.assertEqual(report["results"][-1]["status"], "not_applicable")

    def test_stale_gold_text_is_inapplicable_and_empty_denominators_are_null(self):
        self.services.knowledge.ingest(self.base["id"], "policy.md", b"new policy")
        report = self.run_suite([self.positive()])
        self.assertEqual(report["summary"]["evaluated"], 0)
        self.assertEqual(report["summary"]["not_applicable"], 1)
        for name in ("pass_rate", "top1_hit_rate", "top_k_hit_rate", "negative_accuracy"):
            self.assertIsNone(report["summary"][name])

    def test_position_mismatch_is_failure_even_if_expected_text_was_returned(self):
        self.services.knowledge.ingest(self.base["id"], "policy.md", b"alpha")
        store = self.services.knowledge.store
        original = store._search

        def wrong_position(*args):
            matches = original(*args)
            matches[0]["end_line"] += 1
            return matches

        with patch.object(store, "_search", side_effect=wrong_position):
            report = self.run_suite([self.positive()])
        self.assertEqual(report["results"][0]["rank"], 1)
        self.assertFalse(report["results"][0]["source_positions_valid"])
        self.assertEqual(report["summary"]["passed"], 0)

    def test_all_queries_use_same_read_snapshot_during_document_update(self):
        self.services.knowledge.ingest(self.base["id"], "policy.md", b"alpha old rules")
        store = self.services.knowledge.store
        original = store._search
        calls = []

        def update_after_first_query(*args):
            matches = original(*args)
            if not calls:
                self.services.knowledge.ingest(self.base["id"], "policy.md", b"beta new rules")
            calls.append(True)
            return matches

        with patch.object(store, "_search", side_effect=update_after_first_query):
            report = self.run_suite([self.positive("first"), self.positive("second")])
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertEqual(report["documents"][0]["version"], 1)
        self.assertEqual([row["matches"][0]["document_version"] for row in report["results"]], [1, 1])
        self.assertEqual(store.list_documents(self.base["id"])[0]["version"], 2)

    def test_evaluation_is_read_only_and_does_not_return_other_base_documents(self):
        other = self.services.knowledge.store.create_base("另一个库", "")
        self.services.knowledge.ingest(other["id"], "secret.md", b"privatewordxyz")
        report = self.run_suite([self.negative(query="privatewordxyz"), self.positive(filename="secret.md")])
        self.assertEqual(report["results"][0]["status"], "passed")
        self.assertEqual(report["results"][0]["matches"], [])
        self.assertEqual(report["results"][1]["status"], "not_applicable")
        self.assertEqual(report["documents"], [])
        self.assertNotIn("secret.md", str(report["documents"]))
        with self.services.store.database.connection() as connection:
            for table in ("conversations", "messages", "tool_audit_logs", "pending_actions"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(self.services.knowledge.store.list_documents(other["id"])[0]["version"], 1)

    def test_invalid_suites_and_unknown_base_are_rejected(self):
        cases = [self.positive()]
        for update in [
            {"limit": True}, {"limit": 21}, {"cases": []}, {"cases": cases * 2},
            {"cases": [self.positive(str(index)) for index in range(51)]},
            {"cases": [{**self.negative(), "expected_texts": ["alpha"]}]},
            {"cases": [{**self.positive(), "expected_texts": [""]}]},
            {"cases": [{"id": "bad", "query": "q"}]}, {"unknown": "field"},
        ]:
            suite = {"name": "验证", "cases": copy.deepcopy(cases), **update}
            with self.subTest(update=update):
                self.assertEqual(self.client.post(self.path, json=suite).status_code, 422)
        self.assertEqual(self.client.post("/api/knowledge-evaluations/missing/run", json={"name": "验证", "cases": cases}).status_code, 404)
        self.assertEqual(self.services.knowledge.store.list_bases(), [self.base])

    def test_report_records_actual_chunk_units_and_index_revision_in_fingerprint(self):
        empty = self.run_suite([self.negative()])
        self.assertEqual((empty["chunk_unit"], empty["chunk_size"], empty["chunk_overlap"]), ("none", None, None))
        self.services.knowledge.ingest(self.base["id"], "policy.md", b"# A\nalpha\n\n## B\nbeta\n\n## C\ngamma")
        headings = self.run_suite([self.positive()])
        self.assertEqual(headings["schema_version"], 2)
        self.assertEqual((headings["chunk_unit"], headings["chunk_size"], headings["chunk_overlap"]), ("heading_blocks", 2, 1))
        self.assertEqual(headings["documents"][0]["chunking_strategy"], "markdown_headings")
        self.assertTrue(headings["documents"][0]["indexing_version"])
        # 文档内容与版本不变，但索引策略变化时，旧报告不能被当成同一检索配置。
        with self.services.store.database.connection() as connection:
            connection.execute("UPDATE knowledge_documents SET indexing_version = 'previous-index'")
        changed = self.run_suite([self.positive()])
        self.assertNotEqual(changed["corpus_fingerprint"], headings["corpus_fingerprint"])
        self.assertEqual(changed["documents"][0]["version"], headings["documents"][0]["version"])
        self.services.knowledge.ingest(self.base["id"], "notes.txt", b"notes")
        mixed = self.run_suite([self.positive()])
        self.assertEqual((mixed["chunk_unit"], mixed["chunk_size"], mixed["chunk_overlap"]), ("mixed", None, None))
        self.services.knowledge.delete_document(self.base["id"], headings["documents"][0]["id"])
        characters = self.run_suite([self.negative()])
        self.assertEqual((characters["chunk_unit"], characters["chunk_size"], characters["chunk_overlap"]), ("characters", 800, 100))


if __name__ == "__main__":
    unittest.main()

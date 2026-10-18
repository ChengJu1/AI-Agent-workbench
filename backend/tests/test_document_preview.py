"""文档版本存档、历史预览、精确切片位置及旧数据库升级。"""
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.knowledge_evidence import KnowledgeEvidence


class DocumentPreviewTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.base = self.services.knowledge.store.create_base("笔记 · 预览", "")
        self.original = "😀前言\n\n# Transformer\n注意力负责聚合上下文。\n\n## 后文\n保留这段。"
        self.document = self.services.knowledge.ingest(self.base["id"], "notes.md", self.original.encode())["document"]
        self.path = f'/api/knowledge-bases/{self.base["id"]}/documents/{self.document["id"]}/versions'

    def test_versions_remain_readable_after_update_deletion_and_service_restart(self):
        first = self.client.get(self.path + "/1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["content"], self.original)
        self.services.knowledge.ingest(self.base["id"], "notes.md", b"# Changed\nNew content")
        self.assertEqual(self.client.get(self.path + "/1").json()["content"], self.original)
        self.assertEqual(self.client.get(self.path + "/2").json()["content"], "# Changed\nNew content")
        self.services.knowledge.delete_base(self.base["id"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.knowledge.require_document_version(self.base["id"], self.document["id"], 1)["content"], self.original)
        self.assertEqual(self.client.get(self.path + "/1").status_code, 200)

    def test_citations_include_exact_unicode_offsets_and_snapshot_does_not_include_full_document(self):
        result = self.services.knowledge.search(self.base["id"], "Transformer", 1)
        result.update(knowledge_base_id=self.base["id"], knowledge_base_name=self.base["name"])
        evidence = KnowledgeEvidence()
        evidence.record(result)
        citation = evidence.snapshot()[1]["citations"][0]
        self.assertEqual(self.original[citation["start_offset"]:citation["end_offset"]], citation["content"])
        self.assertNotIn("document_content", citation)

    def test_upgrade_seeds_current_version_idempotently_and_rejects_wrong_base(self):
        database = self.services.store.database
        with database.connection() as connection:
            connection.execute("DROP TABLE knowledge_document_versions")
        database.initialize()
        database.initialize()
        self.assertEqual(self.client.get(self.path + "/1").json()["content"], self.original)
        with database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM knowledge_document_versions").fetchone()[0], 1)
        other_path = self.path.replace(self.base["id"], "other-base")
        self.assertEqual(self.client.get(other_path + "/1").status_code, 404)
        self.assertEqual(self.client.get(self.path + "/99").status_code, 404)
        self.assertEqual(self.client.get(self.path + "/0").status_code, 422)

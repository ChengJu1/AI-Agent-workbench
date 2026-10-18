"""验证建库、上传替换、来源位置、索引一致性及跨知识库隔离。"""
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.document_indexing import split_document
from app.services.knowledge_service import MAX_DOCUMENT_BYTES


class KnowledgeTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        response = self.client.post("/api/knowledge-bases", json={"name": "团队制度", "description": "验证文档入库"})
        self.assertEqual(response.status_code, 201, response.text)
        self.base_id = response.json()["id"]
        self.path = f"/api/knowledge-bases/{self.base_id}"

    def upload(self, content="# GPU 申请制度\n\n申请 GPU 资源需要项目负责人批准。", filename="policy.md", path=None):
        if isinstance(content, str):
            content = content.encode("utf-8")
        return self.client.post((path or self.path) + "/documents", files={"file": (filename, content, "text/plain")})

    def search(self, query, path=None):
        return self.client.post((path or self.path) + "/search", json={"query": query}).json()["matches"]

    def test_upload_builds_index_and_persists_across_service_restart(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()["document"]
        self.assertEqual(document["status"], "ready")
        self.assertGreater(document["chunk_count"], 0)
        self.assertEqual(document["version"], 1)
        self.assertNotIn("content", document)
        base = self.client.get(self.path).json()
        self.assertEqual(base["document_count"], 1)
        self.assertEqual(base["chunk_count"], document["chunk_count"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.knowledge.store.get_base(self.base_id), base)
        self.assertTrue(fresh.knowledge.search(self.base_id, "GPU", 5)["matches"])

    def test_chinese_english_and_single_character_search_include_sources(self):
        self.upload()
        for query in ("GPU", "gpu", "项目负责人", "批准", "申"):
            with self.subTest(query=query):
                matches = self.search(query)
                self.assertTrue(matches)
                self.assertEqual(matches[0]["filename"], "policy.md")
                self.assertEqual(matches[0]["document_version"], 1)
                self.assertIn("GPU", matches[0]["content"])
                self.assertEqual(matches[0]["section"], "GPU 申请制度")
                self.assertGreaterEqual(matches[0]["start_line"], 1)
        self.assertEqual(self.search("不存在的业务xyz"), [])
        self.assertEqual(self.search("💡"), [])

    def test_same_upload_is_idempotent_and_changed_file_replaces_old_index(self):
        original = self.upload("旧词alphaonly 工时规则").json()["document"]
        duplicate = self.upload("旧词alphaonly 工时规则")
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["unchanged"])
        self.assertEqual(duplicate.json()["document"]["version"], 1)
        updated = self.upload("新词betaonly 工时规则")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["document"]["id"], original["id"])
        self.assertEqual(updated.json()["document"]["version"], 2)
        self.assertFalse(updated.json()["unchanged"])
        self.assertEqual(self.search("alphaonly"), [])
        self.assertEqual(self.search("betaonly")[0]["document_version"], 2)
        self.assertEqual(len(self.client.get(self.path + "/documents").json()), 1)

    def test_index_failure_rolls_back_replacement_and_preserves_old_version(self):
        document = self.upload("alphaonly 旧的有效内容").json()["document"]
        with self.services.store.database.connection() as connection:
            connection.execute(
                "CREATE TRIGGER reject_chunks BEFORE INSERT ON knowledge_chunks "
                "BEGIN SELECT RAISE(ABORT, 'test indexing failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.services.knowledge.ingest(self.base_id, "policy.md", b"betaonly new content")
        self.assertEqual(self.services.knowledge.store.get_document(self.base_id, document["id"])["version"], 1)
        self.assertTrue(self.search("alphaonly"))
        self.assertEqual(self.search("betaonly"), [])

    def test_concurrent_duplicate_uploads_create_only_one_document_and_index(self):
        def ingest():
            return self.services.knowledge.ingest(self.base_id, "same.txt", "并发入库 GPU".encode())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: ingest(), range(2)))
        self.assertEqual(sum(result["created"] for result in results), 1)
        self.assertEqual(sum(result["unchanged"] for result in results), 1)
        self.assertEqual(len(self.client.get(self.path + "/documents").json()), 1)
        self.assertEqual(len(self.search("GPU")), 1)

    def test_knowledge_bases_do_not_expose_each_others_documents_or_results(self):
        document = self.upload().json()["document"]
        other = self.client.post("/api/knowledge-bases", json={"name": "另一个知识库"}).json()
        other_path = f'/api/knowledge-bases/{other["id"]}'
        self.assertEqual(self.search("GPU", other_path), [])
        self.assertEqual(self.client.get(other_path + "/documents").json(), [])
        self.assertEqual(self.client.get(other_path + f'/documents/{document["id"]}/chunks').status_code, 404)
        self.assertEqual(self.client.delete(other_path + f'/documents/{document["id"]}').status_code, 404)
        self.assertTrue(self.search("GPU"))

    def test_deleting_document_and_base_removes_all_search_rows(self):
        document = self.upload().json()["document"]
        self.assertEqual(self.client.delete(self.path + f'/documents/{document["id"]}').status_code, 204)
        self.assertEqual(self.search("GPU"), [])
        self.assertEqual(self.client.get(self.path).json()["chunk_count"], 0)
        self.upload()
        self.assertEqual(self.client.delete(self.path).status_code, 204)
        self.assertEqual(self.client.get(self.path).status_code, 404)
        with self.services.store.database.connection() as connection:
            for table in ("knowledge_documents", "knowledge_chunks", "knowledge_chunk_search"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_invalid_uploads_do_not_damage_an_existing_document(self):
        document = self.upload().json()["document"]
        invalid = [
            (b"", "policy.md", 422),
            (b" \n\t", "policy.md", 422),
            (b"\xff\xfe", "policy.md", 422),
            (b"hello\x00world", "policy.md", 422),
            (b"hello", "file.pdf", 415),
            (b"hello", "../outside.md", 422),
            (b"x" * (MAX_DOCUMENT_BYTES + 1), "policy.md", 413),
        ]
        for content, filename, expected in invalid:
            with self.subTest(filename=filename, expected=expected):
                self.assertEqual(self.upload(content, filename).status_code, expected)
        self.assertEqual(self.services.knowledge.store.get_document(self.base_id, document["id"])["version"], 1)
        self.assertTrue(self.search("GPU"))

    def test_bom_and_windows_line_endings_are_normalized_with_correct_sources(self):
        raw = b"\xef\xbb\xbf" + "# 规则\r\n\r\nGPU 必须审批。\r\n".encode()
        document = self.upload(raw, "rules.TXT").json()["document"]
        response = self.client.get(self.path + f'/documents/{document["id"]}/chunks')
        self.assertEqual(response.status_code, 200)
        chunk = response.json()["items"][0]
        self.assertEqual(chunk["content"], "# 规则\n\nGPU 必须审批。")
        self.assertEqual(chunk["start_line"], 1)
        self.assertEqual(chunk["end_line"], 3)

    def test_chunk_preview_is_paginated_and_search_query_is_not_sql(self):
        document = self.upload("\n".join(f"## 规范 {index}\nGPU 申请需要确认。\n" for index in range(8))).json()["document"]
        path = self.path + f'/documents/{document["id"]}/chunks'
        first = self.client.get(path, params={"limit": 2}).json()
        second = self.client.get(path, params={"limit": 2, "offset": 2}).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertGreater(first["total"], 2)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertEqual(self.client.get(path, params={"limit": 101}).status_code, 422)
        self.client.post(self.path + "/search", json={"query": '"; DROP TABLE knowledge_bases; --'})
        self.assertEqual(self.client.get(self.path).status_code, 200)

    def test_blank_base_and_search_and_unknown_paths_are_rejected(self):
        self.assertEqual(self.client.post("/api/knowledge-bases", json={"name": "  "}).status_code, 422)
        self.assertEqual(self.client.post(self.path + "/search", json={"query": "  "}).status_code, 422)
        self.assertEqual(self.client.post(self.path + "/search", json={"query": "x", "limit": True}).status_code, 422)
        for method, path, kwargs in [
            ("get", "/api/knowledge-bases/missing/documents", {}),
            ("post", "/api/knowledge-bases/missing/search", {"json": {"query": "GPU"}}),
            ("delete", "/api/knowledge-bases/missing", {}),
        ]:
            self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 404)


class DocumentSplitTestCase(unittest.TestCase):
    def test_long_heading_metadata_does_not_expand_every_chunk(self):
        text = "# " + "A" * 5000
        chunks = split_document(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], text)
        self.assertTrue(all(len(chunk["section"]) <= 200 for chunk in chunks))

    def test_chunk_positions_cover_source_and_preserve_unicode(self):
        text = "# GPU 规范\n\n" + "申请 GPU 时需说明用途。✅\n" * 200
        chunks = split_document(text, filename="document.txt")
        covered = set()
        self.assertGreater(len(chunks), 1)
        for ordinal, chunk in enumerate(chunks, 1):
            self.assertEqual(chunk["ordinal"], ordinal)
            self.assertLessEqual(len(chunk["content"]), 800)
            self.assertEqual(text[chunk["start_offset"]:chunk["end_offset"]], chunk["content"])
            self.assertEqual(chunk["start_line"], text[:chunk["start_offset"]].count("\n") + 1)
            self.assertEqual(chunk["end_line"], text[:chunk["end_offset"] - 1].count("\n") + 1)
            covered.update(range(chunk["start_offset"], chunk["end_offset"]))
        self.assertTrue(all(index in covered for index, char in enumerate(text) if not char.isspace()))


if __name__ == "__main__":
    unittest.main()

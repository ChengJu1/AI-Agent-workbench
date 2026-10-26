"""验证完整标题块重叠、Markdown 语法边界，以及已有数据的无损索引升级。"""
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.container import build_services
from app.services.document_indexing import INDEXING_VERSION, index_document, split_document
from app.services.knowledge_evidence import KnowledgeEvidence


class MarkdownChunkingTestCase(unittest.TestCase):
    def assert_sources(self, text, chunks):
        covered = set()
        for ordinal, chunk in enumerate(chunks, 1):
            start, end = chunk["start_offset"], chunk["end_offset"]
            self.assertEqual(chunk["ordinal"], ordinal)
            self.assertEqual(text[start:end], chunk["content"])
            self.assertEqual(chunk["start_line"], text[:start].count("\n") + 1)
            self.assertEqual(chunk["end_line"], text[:end - 1].count("\n") + 1)
            covered.update(range(start, end))
        self.assertTrue(all(i in covered for i, char in enumerate(text) if not char.isspace()))

    def test_adjacent_pairs_overlap_exactly_one_complete_block(self):
        blocks = [f"## {title}\n{title} 的完整内容✅。\n\n" for title in "ABCD"]
        text = "".join(blocks)
        chunks = split_document(text)
        self.assertEqual([c["content"] for c in chunks],
                         [(blocks[i] + blocks[i + 1]).strip() for i in range(3)])
        self.assertEqual([c["section"] for c in chunks], ["A → B", "B → C", "C → D"])
        for index in range(2):
            self.assertEqual(text[chunks[index + 1]["start_offset"]:chunks[index]["end_offset"]],
                             blocks[index + 1].strip())
        self.assert_sources(text, chunks)

    def test_preamble_and_each_heading_level_form_blocks_with_parent_paths(self):
        text = "说明\n\n# 制度\n总则\n\n## GPU\n申请\n\n### 审批\n两人\n\n## 存储\n容量"
        chunks = split_document(text)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0]["section"], "前言 → 制度")
        self.assertEqual(chunks[2]["section"], "制度 / GPU → 制度 / GPU / 审批")
        self.assertEqual(chunks[3]["section"], "制度 / GPU / 审批 → 制度 / 存储")
        self.assert_sources(text, chunks)

    def test_code_quotes_lists_and_html_do_not_create_heading_boundaries(self):
        text = ("# 开始\n\n```md\n# 围栏示例\n```\n\n~~~\n## 波浪围栏\n~~~\n\n"
                "    # 缩进代码\n\n> # 引用\n\n- # 列表\n\n"
                "<div>\n# HTML 示例\n</div>\n\n## 结束\n原文")
        chunks = split_document(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["section"], "开始 → 开始 / 结束")
        self.assertEqual(chunks[0]["content"], text)

    def test_setext_and_atx_titles_use_original_source_lines(self):
        text = "总则\n===\n内容\n\n资源\n---\n用途\n\n  ### 审批 ###\n完整原文\n"
        chunks = split_document(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section"], "总则 → 总则 / 资源")
        self.assertEqual(chunks[1]["section"], "总则 / 资源 → 总则 / 资源 / 审批")
        self.assertEqual(chunks[1]["start_line"], 5)
        self.assert_sources(text, chunks)

    def test_yaml_metadata_is_preamble_not_a_setext_heading(self):
        text = "---\ntitle: 规则\n# 元数据注释\n---\n\n# 正文\n说明\n\n## 申请\n流程"
        chunks = split_document(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section"], "前言 → 正文")
        self.assertEqual(chunks[0]["start_line"], 1)
        self.assertEqual(chunks[1]["start_line"], 6)
        self.assert_sources(text, chunks)

    def test_long_blocks_are_split_at_sentence_ends_and_stay_bounded(self):
        text = "# 长章节\n" + "完整内容。" * 500 + "\n\n## 末章\n结尾"
        result = index_document(text, "rules.MARKDOWN")
        self.assertEqual(result.strategy, "markdown_headings")
        self.assertGreater(len(result.chunks), 1)
        self.assertTrue(all(len(chunk["content"]) <= 1600 for chunk in result.chunks))
        self.assertTrue(all(chunk["content"].endswith("。") for chunk in result.chunks[:-1]))
        self.assertEqual(result.chunks[0]["section"], "长章节")
        self.assertEqual(result.chunks[-1]["section"], "长章节 → 长章节 / 末章")
        self.assert_sources(text, result.chunks)

    def test_no_heading_markdown_and_txt_use_character_fallback(self):
        for filename, text in [("no-title.md", "连续正文。" * 500),
                               ("rules.txt", "# 文本标题\n" + "连续正文。" * 500)]:
            with self.subTest(filename=filename):
                result = index_document(text, filename)
                self.assertEqual(result.strategy, "characters")
                self.assertGreater(len(result.chunks), 1)
                self.assertTrue(all(len(c["content"]) <= 800 for c in result.chunks))
                self.assertEqual(result.chunks[0]["end_offset"] - result.chunks[1]["start_offset"], 100)
                self.assert_sources(text, result.chunks)


class MarkdownIndexMigrationTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(database_path=Path(directory.name) / "test.db")
        self.services = build_services(self.settings)
        self.knowledge = self.services.knowledge
        self.store = self.knowledge.store
        self.database = self.store.database
        self.base = self.store.create_base("旧资料", "")
        self.text = "# GPU\n共同审批。\n\n## 工时\n每周提交。\n\n## 存储\n定期清理。"
        # 保存真实的旧字符索引，供升级行为测试；并非先生成新索引再改标记。
        self.document = self.store.save_document(
            self.base["id"], "rules.md", self.text, hashlib.sha256(self.text.encode()).hexdigest(),
            len(self.text.encode()), split_document(self.text, filename="rules.txt"), "", "characters",
        )
        self.document_id = self.document["id"]

    def rows(self, table):
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_legacy_schema_startup_reindexes_without_changing_documents_bindings_or_citations(self):
        with self.database.connection() as connection:
            connection.execute("INSERT INTO agent_knowledge_bases VALUES (?, ?)", ("policy_qa_assistant", self.base["id"]))
            connection.execute("ALTER TABLE knowledge_documents DROP COLUMN indexing_version")
            connection.execute("ALTER TABLE knowledge_documents DROP COLUMN chunking_strategy")
        documents_before = self.rows("knowledge_documents")
        bindings_before = self.rows("agent_knowledge_bases")
        chunks_before = self.rows("knowledge_chunks")
        # 历史来源快照引用旧的 chunk id；重建后仍须可阅读。
        result = self.knowledge.search(self.base["id"], "GPU", 5)
        result.update(knowledge_base_id=self.base["id"], knowledge_base_name=self.base["name"])
        evidence = KnowledgeEvidence()
        evidence.record(result)
        conversation = self.services.store.create("policy_qa_assistant")
        self.services.store.add_message(conversation, "assistant", "需要审批", knowledge=evidence.snapshot()[1])
        messages_before = self.rows("messages")
        fresh = build_services(self.settings)
        documents_after = self.rows("knowledge_documents")
        self.assertEqual([{key: row[key] for key in documents_before[0]} for row in documents_after], documents_before)
        self.assertEqual(documents_after[0]["indexing_version"], INDEXING_VERSION)
        self.assertEqual(documents_after[0]["chunking_strategy"], "markdown_headings")
        self.assertEqual(self.rows("agent_knowledge_bases"), bindings_before)
        self.assertEqual(self.rows("messages"), messages_before)
        chunks_after = self.rows("knowledge_chunks")
        self.assertEqual(len(chunks_after), 2)
        self.assertNotEqual(chunks_before[0]["id"], chunks_after[0]["id"])
        self.assertEqual([r["content"] for r in self.rows("knowledge_chunks")],
                         ["# GPU\n共同审批。\n\n## 工时\n每周提交。", "## 工时\n每周提交。\n\n## 存储\n定期清理。"])
        with self.database.connection() as connection:
            ids = [r[0] for r in connection.execute("SELECT rowid FROM knowledge_chunk_search ORDER BY rowid")]
        self.assertEqual(ids, [r["id"] for r in chunks_after])
        self.assertTrue(fresh.knowledge.search(self.base["id"], "GPU", 5)["matches"])
        build_services(self.settings)
        self.assertEqual(self.rows("knowledge_chunks"), chunks_after)

    def test_reindex_failure_rolls_back_chunks_fts_and_version_marker_then_can_retry(self):
        before = self.rows("knowledge_chunks")
        with self.database.connection() as connection:
            connection.execute("CREATE TRIGGER reject_reindex BEFORE INSERT ON knowledge_chunks "
                               "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.knowledge.reindex_outdated()
        self.assertEqual(self.rows("knowledge_chunks"), before)
        self.assertEqual(self.rows("knowledge_documents")[0]["indexing_version"], "")
        self.assertTrue(self.knowledge.search(self.base["id"], "GPU", 5)["matches"])
        with self.database.connection() as connection:
            connection.execute("DROP TRIGGER reject_reindex")
        self.assertEqual(self.knowledge.reindex_outdated(), 1)
        self.assertEqual(self.knowledge.reindex_outdated(), 0)

    def test_duplicate_upload_updates_stale_index_without_bumping_content_version(self):
        original = self.rows("knowledge_documents")[0]
        response = self.knowledge.ingest(self.base["id"], "rules.md", self.text.encode())
        self.assertTrue(response["unchanged"])
        self.assertFalse(response["created"])
        current = self.rows("knowledge_documents")[0]
        for key in ("id", "content", "content_hash", "version", "created_at", "updated_at"):
            self.assertEqual(current[key], original[key])
        chunks = self.rows("knowledge_chunks")
        self.knowledge.ingest(self.base["id"], "rules.md", self.text.encode())
        self.assertEqual(self.rows("knowledge_chunks"), chunks)

    def test_stale_reindex_does_not_overwrite_a_new_upload_or_recreate_deleted_document(self):
        old = self.store.outdated_documents(INDEXING_VERSION)[0]
        rebuilt = index_document(old["content"], old["filename"])
        self.knowledge.ingest(self.base["id"], "rules.md", b"# Updated\nnewwordxyz")
        self.assertFalse(self.store.reindex_document(old["id"], old["content_hash"], rebuilt.chunks,
                                                     INDEXING_VERSION, rebuilt.strategy))
        self.assertTrue(self.knowledge.search(self.base["id"], "newwordxyz", 5)["matches"])
        self.knowledge.delete_document(self.base["id"], self.document_id)
        self.assertFalse(self.store.reindex_document(old["id"], old["content_hash"], rebuilt.chunks,
                                                     INDEXING_VERSION, rebuilt.strategy))
        self.assertEqual(self.rows("knowledge_chunks"), [])


if __name__ == "__main__":
    unittest.main()

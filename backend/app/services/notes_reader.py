"""只读访问已导入的 Notes，复用工作台的关键词检索及来源合并。"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.services.document_indexing import search_expression
from app.storage.knowledge_store import KnowledgeStore


class ReadOnlyDatabase:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.close()


class NotesReader:
    def __init__(self, database_path, collection_ids=None):
        self.database = ReadOnlyDatabase(database_path)
        self.store = KnowledgeStore(self.database)
        self.collection_ids = None if collection_ids is None else frozenset(collection_ids)

    def list_collections(self):
        return [base for base in self.store.list_bases() if (
            base["id"] in self.collection_ids if self.collection_ids is not None
            else base["name"].startswith("笔记 · ")
        )]

    def require_collection(self, collection_id):
        for base in self.list_collections():
            if base["id"] == collection_id:
                return base
        raise ValueError("笔记分类不存在或未开放，请先调用 list_note_collections。")

    @staticmethod
    def integer(value, name, minimum, maximum):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} 必须是 {minimum}–{maximum} 之间的整数。")

    def list_notes(self, collection_id, offset=0, limit=30):
        self.integer(offset, "offset", 0, 1_000_000)
        self.integer(limit, "limit", 1, 100)
        self.require_collection(collection_id)
        documents = self.store.list_documents(collection_id)
        return {"collection_id": collection_id, "items": documents[offset:offset + limit],
                "total": len(documents), "offset": offset, "limit": limit}

    def search_notes(self, query, collection_id=None, limit=5):
        self.integer(limit, "limit", 1, 10)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
            raise ValueError("query 必须为 1–200 字符的非空关键词。")
        bases = [self.require_collection(collection_id)] if collection_id else self.list_collections()
        expression = search_expression(query.strip())
        results = []
        with self.database.connection() as connection:
            for base in bases:
                result = self.store._retrieve(connection, base["id"], expression, limit)
                # 每个分类单独排名，不把不同查询结果伪装成全局相关性排名。
                results.append({"collection_id": base["id"], "collection_name": base["name"], **result})
        return {"query": query.strip(), "method": "keyword", "limit_per_collection": limit,
                "collections": results}

    def read_note(self, collection_id, note_id, offset=0, limit=12000):
        self.integer(offset, "offset", 0, 10_000_000)
        self.integer(limit, "limit", 1, 20000)
        collection = self.require_collection(collection_id)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, filename, version, content FROM knowledge_documents "
                "WHERE knowledge_base_id = ? AND id = ?", (collection_id, note_id),
            ).fetchone()
        if row is None:
            raise ValueError("笔记不存在，请使用 list_notes 或 search_notes 返回的文档 ID。")
        text = row["content"]
        if offset > len(text):
            raise ValueError("offset 超出正文长度；笔记可能已更新，请从 offset=0 重新读取。")
        end = min(offset + limit, len(text))
        return {"collection_id": collection_id, "collection_name": collection["name"],
                "document_id": row["id"], "filename": row["filename"],
                "document_version": row["version"], "content": text[offset:end],
                "offset": offset, "total_characters": len(text),
                "start_line": text.count("\n", 0, offset) + 1,
                "end_line": text.count("\n", 0, max(offset, end - 1)) + 1,
                "next_offset": end if end < len(text) else None}

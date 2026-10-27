"""原子保存文档、分段和全文索引；替换失败时保留旧版本。"""
from uuid import uuid4
import hashlib
import json
from time import perf_counter

import numpy as np

from app.services.retrieval_postprocessing import (
    CANDIDATE_MULTIPLIER, RELEVANCE_GROUPS, assess_relevance, deduplicate_matches, fuse_rankings,
)


BASE_SELECT = """
    SELECT b.*,
        (SELECT COUNT(*) FROM knowledge_documents d WHERE d.knowledge_base_id = b.id) AS document_count,
        (SELECT COUNT(*) FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
         WHERE d.knowledge_base_id = b.id) AS chunk_count
    FROM knowledge_bases b
"""
DOCUMENT_SELECT = """
    SELECT d.id, d.knowledge_base_id, d.filename, d.byte_size, d.version,
        d.indexing_version, d.chunking_strategy,
        d.created_at, d.updated_at,
        (SELECT COUNT(*) FROM knowledge_chunks c WHERE c.document_id = d.id) AS chunk_count
    FROM knowledge_documents d
"""


class KnowledgeStore:
    def __init__(self, database):
        self.database = database

    def create_base(self, name, description):
        base_id = str(uuid4())
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO knowledge_bases(id, name, description) VALUES (?, ?, ?)",
                (base_id, name, description),
            )
        return self.get_base(base_id)

    def list_bases(self):
        with self.database.connection() as connection:
            rows = connection.execute(BASE_SELECT + " ORDER BY b.created_at, b.rowid").fetchall()
        return [dict(row) for row in rows]

    def get_base(self, base_id):
        with self.database.connection() as connection:
            row = connection.execute(BASE_SELECT + " WHERE b.id = ?", (base_id,)).fetchone()
        return dict(row) if row else None

    def delete_base(self, base_id):
        with self.database.connection() as connection:
            return connection.execute("DELETE FROM knowledge_bases WHERE id = ?", (base_id,)).rowcount == 1

    def list_documents(self, base_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                DOCUMENT_SELECT + " WHERE d.knowledge_base_id = ? ORDER BY d.updated_at DESC, d.rowid DESC",
                (base_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document(self, base_id, document_id):
        with self.database.connection() as connection:
            row = connection.execute(
                DOCUMENT_SELECT + " WHERE d.knowledge_base_id = ? AND d.id = ?", (base_id, document_id)
            ).fetchone()
        return dict(row) if row else None

    def get_document_content(self, base_id, document_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, filename, version, content FROM knowledge_documents WHERE knowledge_base_id = ? AND id = ?",
                (base_id, document_id),
            ).fetchone()
        return dict(row) if row else None

    def get_document_version(self, base_id, document_id, version):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_document_versions WHERE knowledge_base_id = ? "
                "AND document_id = ? AND version = ?", (base_id, document_id, version),
            ).fetchone()
        return dict(row) if row else None

    def _replace_chunks(self, connection, document_id, chunks):
        connection.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
        for chunk in chunks:
            cursor = connection.execute(
                "INSERT INTO knowledge_chunks(document_id, ordinal, content, section, start_offset, "
                "end_offset, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, chunk["ordinal"], chunk["content"], chunk["section"],
                 chunk["start_offset"], chunk["end_offset"], chunk["start_line"], chunk["end_line"]),
            )
            connection.execute(
                "INSERT INTO knowledge_chunk_search(rowid, tokens) VALUES (?, ?)",
                (cursor.lastrowid, chunk["tokens"]),
            )

    def save_document(self, base_id, filename, content, content_hash, byte_size, chunks,
                      indexing_version, chunking_strategy):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM knowledge_bases WHERE id = ?", (base_id,)).fetchone() is None:
                return None
            existing = connection.execute(
                "SELECT id, content_hash, indexing_version, chunking_strategy FROM knowledge_documents "
                "WHERE knowledge_base_id = ? AND filename = ?",
                (base_id, filename),
            ).fetchone()
            same_content = existing is not None and existing["content_hash"] == content_hash
            if (same_content and existing["indexing_version"] == indexing_version
                    and existing["chunking_strategy"] == chunking_strategy):
                return {"id": existing["id"], "created": False, "unchanged": True}
            document_id = existing["id"] if existing else str(uuid4())
            if existing and same_content:
                connection.execute(
                    "UPDATE knowledge_documents SET indexing_version = ?, chunking_strategy = ? WHERE id = ?",
                    (indexing_version, chunking_strategy, document_id),
                )
            elif existing:
                connection.execute(
                    "UPDATE knowledge_documents SET content = ?, content_hash = ?, byte_size = ?, "
                    "version = version + 1, updated_at = CURRENT_TIMESTAMP, indexing_version = ?, "
                    "chunking_strategy = ? WHERE id = ?",
                    (content, content_hash, byte_size, indexing_version, chunking_strategy, document_id),
                )
            else:
                connection.execute(
                    "INSERT INTO knowledge_documents(id, knowledge_base_id, filename, content, content_hash, byte_size, "
                    "indexing_version, chunking_strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (document_id, base_id, filename, content, content_hash, byte_size, indexing_version, chunking_strategy),
                )
            self._replace_chunks(connection, document_id, chunks)
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_document_versions "
                "(document_id, version, knowledge_base_id, knowledge_base_name, filename, content) "
                "SELECT d.id, d.version, d.knowledge_base_id, b.name, d.filename, d.content "
                "FROM knowledge_documents d JOIN knowledge_bases b ON b.id = d.knowledge_base_id WHERE d.id = ?",
                (document_id,),
            )
        return {"id": document_id, "created": existing is None, "unchanged": same_content}

    def outdated_documents(self, indexing_version):
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, filename, content, content_hash FROM knowledge_documents "
                "WHERE indexing_version != ? ORDER BY rowid", (indexing_version,),
            ).fetchall()]

    def reindex_document(self, document_id, expected_hash, chunks, indexing_version, chunking_strategy):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT content_hash, indexing_version FROM knowledge_documents WHERE id = ?", (document_id,),
            ).fetchone()
            if current is None or current["content_hash"] != expected_hash or current["indexing_version"] == indexing_version:
                return False
            self._replace_chunks(connection, document_id, chunks)
            connection.execute(
                "UPDATE knowledge_documents SET indexing_version = ?, chunking_strategy = ? WHERE id = ?",
                (indexing_version, chunking_strategy, document_id),
            )
        return True

    def delete_document(self, base_id, document_id):
        with self.database.connection() as connection:
            return connection.execute(
                "DELETE FROM knowledge_documents WHERE knowledge_base_id = ? AND id = ?",
                (base_id, document_id),
            ).rowcount == 1

    def get_chunks(self, document_id, offset, limit):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_chunks WHERE document_id = ? ORDER BY ordinal LIMIT ? OFFSET ?",
                (document_id, limit, offset),
            ).fetchall()
            count = connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
        return {"items": [dict(row) for row in rows], "total": count, "offset": offset, "limit": limit}

    def search(self, base_id, expression, limit, query_vector=None, model=None, rerank=None):
        with self.database.connection() as connection:
            return self._retrieve(connection, base_id, expression, limit, query_vector, model, rerank)

    def _retrieve(self, connection, base_id, expression, limit, query_vector=None, model=None, rerank=None):
        """rerank(groups) -> 相关度列表；给出时只给前几组打分，判断这次结果是否可能不相关，不改变顺序。"""
        started = perf_counter()
        keyword = self._search(connection, base_id, expression, limit * CANDIDATE_MULTIPLIER)
        vector_ms, vector, coverage = None, [], None
        if query_vector is not None:
            vector_started = perf_counter()
            vector, coverage = self._vector_search(connection, base_id, model, query_vector, limit * CANDIDATE_MULTIPLIER)
            vector_ms = round((perf_counter() - vector_started) * 1000, 3)
        candidates = fuse_rankings(keyword, vector)
        matched = perf_counter()
        groups, skipped = deduplicate_matches(candidates)
        finished = perf_counter()
        rerank_ms, relevance, low_relevance = None, None, None
        if rerank is not None and groups:
            head = groups[:min(RELEVANCE_GROUPS, limit)]
            scores = rerank(head)
            groups, relevance, low_relevance = assess_relevance(groups, scores)
            rerank_ms = round((perf_counter() - finished) * 1000, 3)
        return {
            "matches": groups[:limit],
            "diagnostics": {
                "candidate_count": len(candidates), "unique_count": len(groups), "merge_limit_skipped": skipped,
                "elapsed_ms": round((finished - started) * 1000, 3),
                "deduplication_ms": round((finished - matched) * 1000, 3),
                "keyword_candidates": len(keyword), "vector_candidates": len(vector),
                "vector_ms": vector_ms, "vector_coverage": coverage,
                "rerank_ms": rerank_ms, "relevance_score": None if relevance is None else round(relevance, 4),
                "low_relevance": low_relevance,
            },
        }

    def _vector_search(self, connection, base_id, model, query_vector, limit):
        """在本库已有向量的片段中按余弦相似度取前 limit 个；返回 (片段行, 已有向量的片段占比)。"""
        rows = connection.execute(
            "SELECT c.id, v.vector FROM knowledge_chunk_vectors v JOIN knowledge_chunks c ON c.id = v.chunk_id "
            "JOIN knowledge_documents d ON d.id = c.document_id WHERE d.knowledge_base_id = ? AND v.model = ?",
            (base_id, model),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id "
            "WHERE d.knowledge_base_id = ?", (base_id,),
        ).fetchone()[0]
        coverage = round(len(rows) / total, 4) if total else None
        if not rows:
            return [], coverage
        matrix = np.frombuffer(b"".join(row["vector"] for row in rows), dtype=np.float32).reshape(len(rows), -1)
        scores = matrix @ np.asarray(query_vector, dtype=np.float32)
        order = np.argsort(-scores, kind="stable")[:limit]
        ids = [rows[index]["id"] for index in order]
        found = {row["id"]: dict(row) for row in connection.execute(
            "SELECT c.*, d.filename, d.version AS document_version FROM knowledge_chunks c "
            f"JOIN knowledge_documents d ON d.id = c.document_id WHERE c.id IN ({','.join('?' * len(ids))})", ids,
        )}
        return [{**found[chunk_id], "similarity": round(float(scores[index]), 4)}
                for chunk_id, index in zip(ids, order) if chunk_id in found], coverage

    def chunks_without_vectors(self, model, limit):
        with self.database.connection() as connection:
            # 换了嵌入模型后，旧模型的向量不能和新查询比较，整体删除后重建。
            connection.execute("DELETE FROM knowledge_chunk_vectors WHERE model != ?", (model,))
            return [dict(row) for row in connection.execute(
                "SELECT c.id, c.section, c.content FROM knowledge_chunks c "
                "LEFT JOIN knowledge_chunk_vectors v ON v.chunk_id = c.id WHERE v.chunk_id IS NULL ORDER BY c.id LIMIT ?",
                (limit,),
            )]

    def save_vectors(self, model, chunk_ids, vectors):
        with self.database.connection() as connection:
            # 片段在生成向量期间可能已被替换或删除：只给仍存在的片段写入。
            connection.executemany(
                "INSERT OR REPLACE INTO knowledge_chunk_vectors(chunk_id, model, vector) "
                "SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM knowledge_chunks WHERE id = ?)",
                [(chunk_id, model, np.asarray(vector, dtype=np.float32).tobytes(), chunk_id)
                 for chunk_id, vector in zip(chunk_ids, vectors)],
            )

    def _search(self, connection, base_id, expression, limit):
        if not expression:
            return []
        rows = connection.execute(
            "SELECT c.*, d.filename, d.version AS document_version, -bm25(knowledge_chunk_search) AS keyword_score "
            "FROM knowledge_chunk_search JOIN knowledge_chunks c ON c.id = knowledge_chunk_search.rowid "
            "JOIN knowledge_documents d ON d.id = c.document_id "
            "WHERE knowledge_chunk_search MATCH ? AND d.knowledge_base_id = ? "
            "ORDER BY bm25(knowledge_chunk_search), c.id LIMIT ?",
            (expression, base_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def evaluation_snapshot(self, base_id, expressions, limit, query_vectors=None, model=None, rerankers=None):
        # 所有查询与文档来源检查共享一个 SQLite 读快照，避免评估中途版本变化。
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            base = connection.execute("SELECT * FROM knowledge_bases WHERE id = ?", (base_id,)).fetchone()
            if base is None:
                return None
            documents = [dict(row) for row in connection.execute(
                "SELECT id, filename, version, content_hash, content, indexing_version, chunking_strategy FROM knowledge_documents "
                "WHERE knowledge_base_id = ? ORDER BY filename", (base_id,),
            ).fetchall()]
            corpus = [list(row) for row in connection.execute(
                "SELECT id, version, content_hash, indexing_version, chunking_strategy FROM knowledge_documents ORDER BY id"
            ).fetchall()]
            fingerprint = hashlib.sha256(json.dumps(corpus, separators=(",", ":")).encode()).hexdigest()
            chunk_count = connection.execute("SELECT COUNT(*) FROM knowledge_chunk_search").fetchone()[0]
            vectors = query_vectors or [None] * len(expressions)
            rerankers = rerankers or [None] * len(expressions)
            retrievals = [self._retrieve(connection, base_id, expression, limit, vector, model, rerank)
                          for expression, vector, rerank in zip(expressions, vectors, rerankers)]
            return {"base": dict(base), "documents": documents, "retrievals": retrievals,
                    "corpus_fingerprint": fingerprint, "index_chunk_count": chunk_count}

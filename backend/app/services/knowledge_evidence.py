"""隔离每一轮的检索证据与引用编号；SDK 工具可能在线程中并发执行。"""
from threading import Lock
from uuid import uuid4
import hashlib

from app.models.evidence import KnowledgeCitation, KnowledgeEvidenceInfo


class KnowledgeEvidence:
    def __init__(self):
        self._prefix = uuid4().hex[:12]
        self._lock = Lock()
        self._citations = {}
        self._queries = []
        self._successes = 0
        self._failures = 0
        self._revision = 0

    def record(self, result):
        with self._lock:
            self._successes += 1
            self._queries.append(result["query"])
            matches = []
            for match in result["matches"]:
                # 同一代表 chunk 可在不同查询中合并出不同范围，已发出的引用快照不可被复用或覆盖。
                key = (result["knowledge_base_id"], match["document_id"], match["document_version"],
                       match["start_offset"], match["end_offset"], hashlib.sha256(match["content"].encode()).digest())
                if key not in self._citations:
                    self._citations[key] = KnowledgeCitation(
                        citation_id=f"S{self._prefix}-{len(self._citations) + 1}",
                        knowledge_base_id=result["knowledge_base_id"], knowledge_base_name=result["knowledge_base_name"],
                        document_id=match["document_id"], document_version=match["document_version"],
                        chunk_id=match["id"], filename=match["filename"], section=match["section"],
                        start_line=match["start_line"], end_line=match["end_line"], content=match["content"],
                    )
                citation = self._citations[key]
                matches.append({**match, "citation_id": citation.citation_id,
                                "citation_link": f"#source-{citation.citation_id}"})
            self._revision += 1
            return {**result, "matches": matches}

    def record_failure(self):
        with self._lock:
            self._failures += 1
            self._revision += 1

    def snapshot(self):
        with self._lock:
            status = ("matched" if self._citations else "no_match" if self._successes
                      else "failed" if self._failures else "not_searched")
            return self._revision, KnowledgeEvidenceInfo(
                status=status, citations=list(self._citations.values()),
                queries=list(self._queries), failed_searches=self._failures,
            ).model_dump()

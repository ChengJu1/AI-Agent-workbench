"""只读评估现有检索器，不调用模型，也不修改题集来掩盖失败。"""
from datetime import datetime, timezone
from time import perf_counter

from app.config import BACKEND_DIRECTORY
from app.errors import ServiceError
from app.models.evaluation import RetrievalSuite
from app.services.document_indexing import CHARACTER_STRATEGY, CHUNK_OVERLAP, CHUNK_SIZE, MARKDOWN_STRATEGY, search_expression
from app.services.retrieval_postprocessing import CANDIDATE_MULTIPLIER, MAX_MERGED_CHARACTERS, RETRIEVAL_POLICY


def sample_suite():
    return RetrievalSuite.model_validate_json(
        (BACKEND_DIRECTORY / "evaluations" / "team-collaboration-v1.json").read_text(encoding="utf-8")
    )


def source_valid(match, documents):
    document = documents.get(match["document_id"])
    if document is None or document["filename"] != match["filename"] or document["version"] != match["document_version"]:
        return False
    text = document["content"]
    start, end = match["start_offset"], match["end_offset"]
    return (0 <= start < end <= len(text) and text[start:end] == match["content"]
            and match["start_line"] == text[:start].count("\n") + 1
            and match["end_line"] == text[:end - 1].count("\n") + 1)


class RetrievalEvaluationService:
    def __init__(self, store):
        self.store = store

    def run(self, base_id, suite):
        started = perf_counter()
        snapshot = self.store.evaluation_snapshot(base_id, [search_expression(case.query) for case in suite.cases], suite.limit)
        if snapshot is None:
            raise ServiceError("知识库不存在。", 404)
        documents = {document["id"]: document for document in snapshot["documents"]}
        by_filename = {document["filename"]: document for document in snapshot["documents"]}
        results = []
        for case, retrieval in zip(suite.cases, snapshot["retrievals"]):
            matches = retrieval["matches"]
            positions_valid = all(source_valid(match, documents) for match in matches)
            rank = None
            if case.expect_no_match:
                status = "passed" if not matches else "failed"
                reason = "正确返回空结果" if not matches else "预期没有匹配，实际返回了片段"
            elif case.expected_filename not in by_filename:
                status, reason = "not_applicable", "缺少预期文档，请上传对应文档或导入适用于当前库的题集"
            elif not all(text in by_filename[case.expected_filename]["content"] for text in case.expected_texts):
                status, reason = "not_applicable", "预期关键原文不在当前文档中，请核对文档版本或更新题集"
            else:
                rank = next((index for index, match in enumerate(matches, 1)
                             if match["filename"] == case.expected_filename
                             and all(text in match["content"] for text in case.expected_texts)), None)
                if not positions_valid:
                    status, reason = "failed", "返回片段的原文位置或版本与文档不一致"
                elif rank is not None:
                    status, reason = "passed", f"第 {rank} 条命中目标文档和全部关键原文"
                else:
                    status, reason = "failed", f"前 {suite.limit} 条未找到包含全部关键原文的目标片段"
            results.append({"case": case.model_dump(), "status": status, "reason": reason, "rank": rank,
                            "source_positions_valid": positions_valid, "matches": matches,
                            "diagnostics": retrieval["diagnostics"]})
        evaluated = [result for result in results if result["status"] != "not_applicable"]
        positives = [result for result in evaluated if not result["case"]["expect_no_match"]]
        negatives = [result for result in evaluated if result["case"]["expect_no_match"]]
        passed = sum(result["status"] == "passed" for result in evaluated)
        top1 = sum(result["rank"] == 1 for result in positives)
        top_k = sum(result["rank"] is not None for result in positives)
        negative_correct = sum(result["status"] == "passed" for result in negatives)
        strategies = {document["chunking_strategy"] for document in snapshot["documents"]}
        if strategies == {MARKDOWN_STRATEGY}:
            chunk_unit, chunk_size, chunk_overlap = "heading_blocks", 2, 1
        elif strategies == {CHARACTER_STRATEGY}:
            chunk_unit, chunk_size, chunk_overlap = "characters", CHUNK_SIZE, CHUNK_OVERLAP
        else:
            chunk_unit, chunk_size, chunk_overlap = "mixed" if strategies else "none", None, None
        return {
            "schema_version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
            "knowledge_base_id": base_id, "knowledge_base_name": snapshot["base"]["name"],
            "suite": suite.model_dump(), "method": "keyword_bm25", "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap, "chunk_unit": chunk_unit, "corpus_fingerprint": snapshot["corpus_fingerprint"],
            "index_chunk_count": snapshot["index_chunk_count"],
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "average_retrieval_ms": round(sum(row["diagnostics"]["elapsed_ms"] for row in results) / len(results), 3),
            "retrieval_policy": RETRIEVAL_POLICY, "candidate_multiplier": CANDIDATE_MULTIPLIER,
            "max_merged_characters": MAX_MERGED_CHARACTERS,
            "documents": [{key: doc[key] for key in ("id", "filename", "version", "content_hash", "indexing_version", "chunking_strategy")}
                          for doc in snapshot["documents"]],
            "summary": {
                "total": len(results), "evaluated": len(evaluated), "passed": passed,
                "failed": len(evaluated) - passed, "not_applicable": len(results) - len(evaluated),
                "positive_evaluated": len(positives), "top1_hits": top1, "top_k_hits": top_k,
                "negative_evaluated": len(negatives), "negative_correct": negative_correct,
                "pass_rate": passed / len(evaluated) if evaluated else None,
                "top1_hit_rate": top1 / len(positives) if positives else None,
                "top_k_hit_rate": top_k / len(positives) if positives else None,
                "negative_accuracy": negative_correct / len(negatives) if negatives else None,
            },
            "results": results,
        }

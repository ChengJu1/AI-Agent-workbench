"""可导入的检索题集和可复现的评估报告。"""
from typing import Literal

from pydantic import Field, model_validator

from app.models.api import RequestModel
from app.models.knowledge import KnowledgeSearchMatch, SearchDiagnostics


class RetrievalCase(RequestModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    query: str = Field(min_length=1, max_length=200)
    category: Literal["keyword", "question", "paraphrase", "negative"] = "keyword"
    expected_filename: str | None = Field(default=None, min_length=1, max_length=200)
    expected_texts: list[str] = Field(default_factory=list, max_length=8)
    expect_no_match: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_expectation(self):
        if any(not text or len(text) > 200 for text in self.expected_texts):
            raise ValueError("预期原文须为 1–200 字符的非空字符串")
        if self.expect_no_match:
            if self.expected_filename or self.expected_texts:
                raise ValueError("空结果题不能同时指定预期文件或原文")
        elif not self.expected_filename or not self.expected_texts:
            raise ValueError("正例题必须指定预期文件和至少一段关键原文")
        return self


class RetrievalSuite(RequestModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    limit: int = Field(default=5, ge=1, le=20, strict=True)
    cases: list[RetrievalCase] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("评估题 ID 不能重复")
        return self


class RetrievalCaseResult(RequestModel):
    case: RetrievalCase
    status: Literal["passed", "failed", "not_applicable"]
    reason: str
    rank: int | None = None
    source_positions_valid: bool
    matches: list[KnowledgeSearchMatch]
    diagnostics: SearchDiagnostics


class EvaluationSummary(RequestModel):
    total: int
    evaluated: int
    passed: int
    failed: int
    not_applicable: int
    positive_evaluated: int
    top1_hits: int
    top_k_hits: int
    negative_evaluated: int
    negative_correct: int
    pass_rate: float | None
    top1_hit_rate: float | None
    top_k_hit_rate: float | None
    negative_accuracy: float | None


class EvaluationDocument(RequestModel):
    id: str
    filename: str
    version: int
    content_hash: str
    indexing_version: str
    chunking_strategy: str


class RetrievalReport(RequestModel):
    schema_version: Literal[2] = 2
    created_at: str
    knowledge_base_id: str
    knowledge_base_name: str
    suite: RetrievalSuite
    method: Literal["keyword_bm25", "hybrid_rrf"] = "keyword_bm25"
    embedding_model: str | None = None
    rerank_model: str | None = None
    chunk_size: int | None
    chunk_overlap: int | None
    chunk_unit: Literal["heading_blocks", "characters", "mixed", "none"]
    corpus_fingerprint: str
    index_chunk_count: int
    elapsed_ms: float = Field(ge=0)
    average_retrieval_ms: float = Field(ge=0)
    retrieval_policy: str
    candidate_multiplier: int
    max_merged_characters: int
    documents: list[EvaluationDocument]
    summary: EvaluationSummary
    results: list[RetrievalCaseResult]

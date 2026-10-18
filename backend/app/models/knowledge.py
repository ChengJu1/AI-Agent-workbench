"""知识库、文档入库和带来源的检索结果。"""
from typing import Literal

from pydantic import BaseModel, Field

from app.models.api import RequestModel


class CreateKnowledgeBaseRequest(RequestModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


class KnowledgeBaseInfo(BaseModel):
    id: str
    name: str
    description: str
    document_count: int
    chunk_count: int
    created_at: str


class KnowledgeDocumentInfo(BaseModel):
    id: str
    knowledge_base_id: str
    filename: str
    byte_size: int
    version: int
    indexing_version: str
    chunking_strategy: str
    chunk_count: int
    status: Literal["ready"] = "ready"
    created_at: str
    updated_at: str


class DocumentUploadResult(BaseModel):
    document: KnowledgeDocumentInfo
    created: bool
    unchanged: bool


class KnowledgeChunkInfo(BaseModel):
    id: int
    document_id: str
    ordinal: int
    content: str
    section: str
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int


class KnowledgeChunkPage(BaseModel):
    items: list[KnowledgeChunkInfo]
    total: int
    offset: int
    limit: int


class SearchKnowledgeRequest(RequestModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20, strict=True)


class KnowledgeSearchMatch(KnowledgeChunkInfo):
    filename: str
    document_version: int
    source_chunk_ids: list[int] = Field(default_factory=list)


class SearchDiagnostics(BaseModel):
    candidate_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    merge_limit_skipped: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    deduplication_ms: float = Field(ge=0)


class KnowledgeSearchResult(BaseModel):
    query: str
    method: Literal["keyword"] = "keyword"
    matches: list[KnowledgeSearchMatch]
    diagnostics: SearchDiagnostics

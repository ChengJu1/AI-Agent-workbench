"""回答引用使用本轮检索快照，不依赖之后可能被替换或删除的文档。"""
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeCitation(BaseModel):
    citation_id: str
    knowledge_base_id: str
    knowledge_base_name: str
    document_id: str
    document_version: int
    chunk_id: int
    filename: str
    section: str
    start_line: int
    end_line: int
    content: str


class KnowledgeEvidenceInfo(BaseModel):
    status: Literal["matched", "no_match", "not_searched", "failed"]
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    failed_searches: int = 0

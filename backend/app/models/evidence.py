"""回答引用使用本轮检索快照，不依赖之后可能被替换或删除的文档。"""
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeCitation(BaseModel):
    citation_id: str = Field(pattern=r"^S[0-9a-f]{12}-[1-9]\d*$")
    knowledge_base_id: str = Field(min_length=1)
    knowledge_base_name: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: int = Field(ge=1, strict=True)
    chunk_id: int | None = Field(default=None, ge=1, strict=True)
    source_kind: Literal["knowledge", "notes_mcp"] = "knowledge"
    filename: str = Field(min_length=1)
    section: str
    start_line: int = Field(ge=1, strict=True)
    end_line: int = Field(ge=1, strict=True)
    content: str = Field(min_length=1)
    start_offset: int | None = Field(default=None, ge=0, strict=True)
    end_offset: int | None = Field(default=None, ge=0, strict=True)


class KnowledgeEvidenceInfo(BaseModel):
    status: Literal["matched", "no_match", "not_searched", "failed"]
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    failed_searches: int = Field(default=0, ge=0, strict=True)
    channels: list[Literal["knowledge", "notes_mcp"]] = Field(default_factory=list)
    notes_calls: int = Field(default=0, ge=0, strict=True)

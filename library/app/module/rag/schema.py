"""Request and response models for the retrieval corpus."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IndexTextRequest(BaseModel):
    title: str = Field(max_length=300, description="文献标题")
    text: str = Field(min_length=1, description="正文，将被切分并向量化")
    book_id: str | None = Field(default=None, description="关联书目 ID")
    source: str = Field(default="upload", description="catalog / fulltext / policy / upload")


class DocResponse(BaseModel):
    id: str
    book_id: str | None = None
    title: str
    source: str
    status: str
    chunk_count: int = 0
    error_msg: str | None = None
    created_at: datetime
    updated_at: datetime


class Passage(BaseModel):
    """One retrieved passage, with everything a citation needs."""

    chunk_id: str
    doc_id: str
    doc_title: str | None = None
    book_id: str | None = None
    book_title: str | None = None
    chunk_index: int = 0
    content: str
    score: float = Field(description="余弦相似度，越大越相关")


class SearchResponse(BaseModel):
    query: str
    passages: list[Passage] = Field(default_factory=list)

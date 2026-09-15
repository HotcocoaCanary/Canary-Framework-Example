"""Request and response models for the librarian assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.module.rag.schema import Passage


class CreateChatSessionRequest(BaseModel):
    title: str = Field(default="新会话", max_length=200, description="会话标题")
    reader_id: Optional[str] = Field(default=None, description="归属读者，可留空")


class ChatSessionResponse(BaseModel):
    id: str
    reader_id: Optional[str] = None
    title: str
    created_at: datetime
    updated_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="读者的问题")
    top_k: Optional[int] = Field(default=None, ge=1, le=20, description="检索片段数")
    book_id: Optional[str] = Field(default=None, description="限定在某本书的资料中作答")


class AnswerResponse(BaseModel):
    session_id: Optional[str] = None
    question: str
    answer: str
    sources: list[Passage] = Field(default_factory=list, description="作答依据的馆藏片段")
    grounded: bool = Field(description="是否检索到可用资料")


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    sources: Optional[list[dict]] = None
    created_at: datetime

"""Request and response models for the catalogue."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateBookRequest(BaseModel):
    title: str = Field(max_length=300, description="书名")
    author: str = Field(max_length=200, description="作者")
    isbn: Optional[str] = Field(default=None, max_length=20, description="ISBN")
    subtitle: Optional[str] = Field(default=None, max_length=300, description="副标题")
    publisher: Optional[str] = Field(default=None, max_length=200, description="出版社")
    published_year: Optional[int] = Field(default=None, ge=0, le=2200, description="出版年份")
    category: str = Field(default="未分类", max_length=100, description="分类")
    language: str = Field(default="zh", max_length=16, description="语种")
    summary: Optional[str] = Field(default=None, description="内容简介")
    tags: Optional[list[str]] = Field(default=None, description="标签")
    copies: int = Field(default=0, ge=0, le=100, description="同时入藏的副本数")
    location: str = Field(default="总馆", max_length=120, description="副本馆藏位置")


class UpdateBookRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    author: Optional[str] = Field(default=None, max_length=200)
    subtitle: Optional[str] = Field(default=None, max_length=300)
    publisher: Optional[str] = Field(default=None, max_length=200)
    published_year: Optional[int] = Field(default=None, ge=0, le=2200)
    category: Optional[str] = Field(default=None, max_length=100)
    language: Optional[str] = Field(default=None, max_length=16)
    summary: Optional[str] = Field(default=None)
    tags: Optional[list[str]] = Field(default=None)


class HoldingsSummary(BaseModel):
    total: int = Field(default=0, description="馆藏副本总数")
    available: int = Field(default=0, description="可借数量")
    on_loan: int = Field(default=0, description="在借数量")
    unavailable: int = Field(default=0, description="遗失/维修/下架数量")
    reservations: int = Field(default=0, description="排队预约人数")


class BookResponse(BaseModel):
    id: str
    isbn: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    author: str
    publisher: Optional[str] = None
    published_year: Optional[int] = None
    category: str
    language: str
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    holdings: HoldingsSummary = Field(default_factory=HoldingsSummary)
    created_at: datetime
    updated_at: datetime


class AddCopiesRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100, description="入藏数量")
    location: str = Field(default="总馆", max_length=120, description="馆藏位置")


class UpdateCopyRequest(BaseModel):
    status: Optional[str] = Field(
        default=None, description="available / lost / repairing / withdrawn"
    )
    location: Optional[str] = Field(default=None, max_length=120)


class CopyResponse(BaseModel):
    id: str
    book_id: str
    barcode: str
    location: str
    status: str
    acquired_at: datetime


class CategoryCount(BaseModel):
    category: str
    books: int

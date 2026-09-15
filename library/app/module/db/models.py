"""The library domain — catalogue, holdings, readers, circulation and RAG corpus.

Two clusters share one schema:

* **circulation** — ``Book`` (a bibliographic record) has many ``BookCopy``
  (physical holdings).  A ``Reader`` borrows a *copy*, which produces a ``Loan``;
  when every copy of a book is out, a ``Reservation`` queues the reader.
* **RAG** — ``LibraryDoc`` is an indexable text (a book's full text, its blurb,
  or a library policy) that is split into ``DocChunk`` rows carrying an
  embedding.  ``ChatSession`` / ``ChatMessage`` hold the librarian-assistant
  conversations, with the retrieved passages recorded on the answer.

The embedding column is a pgvector ``VECTOR(1024)`` on PostgreSQL and a JSON
array on SQLite, so the identical model runs against both.
"""

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, BigInteger, Column, Text
from sqlmodel import Field, SQLModel

EMBEDDING_DIM = 1024


def _embedding_column() -> Column:
    """pgvector on PostgreSQL, JSON array on SQLite — one model, two dialects."""
    return Column(
        Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite"),
        nullable=True,
    )


def utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)


# --- 书目与馆藏 ---------------------------------------------------------


class Book(SQLModel, table=True):
    """A bibliographic record — one row per title, not per physical volume."""

    __tablename__ = "books"

    id: str = Field(primary_key=True, max_length=32)
    isbn: Optional[str] = Field(default=None, max_length=20, index=True)
    title: str = Field(max_length=300, index=True)
    subtitle: Optional[str] = Field(default=None, max_length=300)
    author: str = Field(max_length=200, index=True)
    publisher: Optional[str] = Field(default=None, max_length=200)
    published_year: Optional[int] = Field(default=None)
    category: str = Field(default="未分类", max_length=100, index=True)
    language: str = Field(default="zh", max_length=16)
    summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    tags: Optional[list[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BookCopy(SQLModel, table=True):
    """A physical holding — the thing that is actually borrowed."""

    __tablename__ = "book_copies"

    id: str = Field(primary_key=True, max_length=32)
    book_id: str = Field(max_length=32, index=True)
    barcode: str = Field(max_length=64, index=True, unique=True)
    location: str = Field(default="总馆", max_length=120)
    # available / on_loan / reserved / lost / repairing / withdrawn
    status: str = Field(default="available", max_length=16, index=True)
    acquired_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --- 读者 ---------------------------------------------------------------


class Reader(SQLModel, table=True):
    """A library card holder."""

    __tablename__ = "readers"

    id: str = Field(primary_key=True, max_length=32)
    card_no: str = Field(max_length=32, index=True, unique=True)
    name: str = Field(max_length=100, index=True)
    email: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=40)
    # student / normal / vip / staff
    level: str = Field(default="normal", max_length=16)
    # active / suspended
    status: str = Field(default="active", max_length=16, index=True)
    fine_balance_cents: int = Field(default=0, sa_column=Column(BigInteger, default=0))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --- 流通 ---------------------------------------------------------------


class Loan(SQLModel, table=True):
    """One borrow-and-return cycle for a single copy."""

    __tablename__ = "loans"

    id: str = Field(primary_key=True, max_length=32)
    copy_id: str = Field(max_length=32, index=True)
    book_id: str = Field(max_length=32, index=True)
    reader_id: str = Field(max_length=32, index=True)
    borrowed_at: datetime = Field(default_factory=utcnow)
    due_at: datetime = Field(index=True)
    returned_at: Optional[datetime] = Field(default=None)
    renew_count: int = Field(default=0)
    # active / returned / lost
    status: str = Field(default="active", max_length=16, index=True)
    fine_cents: int = Field(default=0)


class Reservation(SQLModel, table=True):
    """A hold placed on a *title* while every copy is out."""

    __tablename__ = "reservations"

    id: str = Field(primary_key=True, max_length=32)
    book_id: str = Field(max_length=32, index=True)
    reader_id: str = Field(max_length=32, index=True)
    # waiting / ready / fulfilled / cancelled / expired
    status: str = Field(default="waiting", max_length=16, index=True)
    copy_id: Optional[str] = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=utcnow)
    ready_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)


# --- RAG 语料 -----------------------------------------------------------


class LibraryDoc(SQLModel, table=True):
    """An indexable text: a book's content, its blurb, or a library policy."""

    __tablename__ = "library_docs"

    id: str = Field(primary_key=True, max_length=32)
    book_id: Optional[str] = Field(default=None, max_length=32, index=True)
    title: str = Field(max_length=300)
    # catalog / fulltext / policy / upload
    source: str = Field(default="upload", max_length=20, index=True)
    text: str = Field(sa_column=Column(Text))
    # pending / indexed / failed
    status: str = Field(default="pending", max_length=16, index=True)
    error_msg: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    chunk_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DocChunk(SQLModel, table=True):
    """A retrievable passage with its embedding."""

    __tablename__ = "doc_chunks"

    id: str = Field(primary_key=True, max_length=32)
    doc_id: str = Field(max_length=32, index=True)
    book_id: Optional[str] = Field(default=None, max_length=32, index=True)
    chunk_index: int = Field(default=0)
    content: str = Field(sa_column=Column(Text))
    embedding: Optional[list[float]] = Field(default=None, sa_column=_embedding_column())
    created_at: datetime = Field(default_factory=utcnow)


# --- 智能馆员会话 -------------------------------------------------------


class ChatSession(SQLModel, table=True):
    """A conversation with the librarian assistant."""

    __tablename__ = "chat_sessions"

    id: str = Field(primary_key=True, max_length=32)
    reader_id: Optional[str] = Field(default=None, max_length=32, index=True)
    title: str = Field(default="新会话", max_length=200)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    """One turn; ``sources`` records the passages an answer was grounded in."""

    __tablename__ = "chat_messages"

    id: str = Field(primary_key=True, max_length=32)
    session_id: str = Field(max_length=32, index=True)
    role: str = Field(max_length=10)
    content: str = Field(sa_column=Column(Text))
    sources: Optional[list[dict]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow)

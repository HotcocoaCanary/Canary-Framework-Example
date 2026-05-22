from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlmodel import SQLModel, Field, Column, JSON, BigInteger, Text


class KnowledgeBase(SQLModel, table=True):
    __tablename__ = "knowledge_bases"
    id: str = Field(primary_key=True, max_length=32)
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    permission: str = Field(default="private", max_length=10)
    share_token: Optional[str] = Field(default=None, max_length=64, nullable=True)
    created_by: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KbMember(SQLModel, table=True):
    __tablename__ = "kb_members"
    kb_id: str = Field(primary_key=True, max_length=32)
    user_id: str = Field(primary_key=True, max_length=64)
    role: str = Field(default="member", max_length=10)
    joined_at: datetime = Field(default_factory=datetime.utcnow)


class KbNode(SQLModel, table=True):
    __tablename__ = "kb_nodes"
    id: str = Field(primary_key=True, max_length=32)
    kb_id: str = Field(max_length=32, index=True)
    name: str = Field(max_length=500)
    node_type: Optional[str] = Field(default=None, max_length=20, nullable=True)
    size: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    parent_path: Optional[str] = Field(default=None, max_length=1000, nullable=True)
    full_path: str = Field(max_length=1000)
    oss_key: Optional[str] = Field(default=None, max_length=1000, nullable=True)
    oss_url: Optional[str] = Field(default=None, max_length=2000, nullable=True)
    created_by: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KbFileRecord(SQLModel, table=True):
    __tablename__ = "kb_file_records"
    file_id: str = Field(primary_key=True, max_length=32)
    status: str = Field(default="pending", max_length=20)
    parsed_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    error_msg: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    parse_task_id: Optional[str] = Field(default=None, max_length=32, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ParseTask(SQLModel, table=True):
    __tablename__ = "parse_tasks"
    id: str = Field(primary_key=True, max_length=32)
    kb_id: str = Field(max_length=32, index=True)
    created_by: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KbChunk(SQLModel, table=True):
    __tablename__ = "kb_chunks"
    id: str = Field(primary_key=True, max_length=32)
    file_id: str = Field(max_length=32, index=True)
    kb_id: str = Field(max_length=32, index=True)
    content: str = Field(sa_column=Column(Text))
    embedding: Optional[list[float]] = Field(default=None, sa_column=Column(Vector(1024), nullable=True))
    chunk_index: int = Field(default=0)
    page: Optional[int] = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(primary_key=True, max_length=32)
    user_id: str = Field(max_length=64, index=True)
    name: Optional[str] = Field(default=None, max_length=200, nullable=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: str = Field(primary_key=True, max_length=32)
    session_id: str = Field(max_length=32, index=True)
    role: str = Field(max_length=10)
    content: str = Field(sa_column=Column(Text))
    sources: Optional[list[dict]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)

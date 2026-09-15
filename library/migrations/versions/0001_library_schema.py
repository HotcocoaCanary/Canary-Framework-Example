"""智能图书馆管理系统 initial schema.

Creates the circulation cluster (books / copies / readers / loans / reservations)
and the RAG cluster (library_docs / doc_chunks / chat_sessions / chat_messages),
plus the ``vector`` extension the embedding column needs.

Revision ID: 0001_library_schema
Revises:
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import pgvector
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001_library_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "books",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("isbn", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column("subtitle", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=True),
        sa.Column("author", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("publisher", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("language", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_books_isbn", "books", ["isbn"])
    op.create_index("ix_books_title", "books", ["title"])
    op.create_index("ix_books_author", "books", ["author"])
    op.create_index("ix_books_category", "books", ["category"])

    op.create_table(
        "book_copies",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("book_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("barcode", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_book_copies_book_id", "book_copies", ["book_id"])
    op.create_index("ix_book_copies_barcode", "book_copies", ["barcode"], unique=True)
    op.create_index("ix_book_copies_status", "book_copies", ["status"])

    op.create_table(
        "readers",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("card_no", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.Column("level", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("fine_balance_cents", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_readers_card_no", "readers", ["card_no"], unique=True)
    op.create_index("ix_readers_name", "readers", ["name"])
    op.create_index("ix_readers_status", "readers", ["status"])

    op.create_table(
        "loans",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("copy_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("book_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("reader_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("borrowed_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("renew_count", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("fine_cents", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_loans_copy_id", "loans", ["copy_id"])
    op.create_index("ix_loans_book_id", "loans", ["book_id"])
    op.create_index("ix_loans_reader_id", "loans", ["reader_id"])
    op.create_index("ix_loans_due_at", "loans", ["due_at"])
    op.create_index("ix_loans_status", "loans", ["status"])

    op.create_table(
        "reservations",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("book_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("reader_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("copy_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reservations_book_id", "reservations", ["book_id"])
    op.create_index("ix_reservations_reader_id", "reservations", ["reader_id"])
    op.create_index("ix_reservations_status", "reservations", ["status"])

    op.create_table(
        "library_docs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("book_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_library_docs_book_id", "library_docs", ["book_id"])
    op.create_index("ix_library_docs_status", "library_docs", ["status"])

    op.create_table(
        "doc_chunks",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("doc_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("book_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doc_chunks_doc_id", "doc_chunks", ["doc_id"])
    op.create_index("ix_doc_chunks_book_id", "doc_chunks", ["book_id"])
    # 近似最近邻索引：余弦距离，对应 DocChunkRepository._search_pgvector
    op.execute(
        "CREATE INDEX ix_doc_chunks_embedding_cosine ON doc_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("reader_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_reader_id", "chat_sessions", ["reader_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("doc_chunks")
    op.drop_table("library_docs")
    op.drop_table("reservations")
    op.drop_table("loans")
    op.drop_table("readers")
    op.drop_table("book_copies")
    op.drop_table("books")

"""Passage queries — including the similarity search that drives retrieval.

The search has two implementations picked from the live dialect:

* **PostgreSQL** — ``pgvector``'s cosine-distance operator, ordered and limited
  in the database.
* **SQLite** — candidate passages are loaded and scored in Python.

The model column is declared once (``Vector(1024)`` with a JSON variant), so the
same rows round-trip through either backend.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.infra.ai import cosine
from app.infra.db import Database
from app.module.db.models import DocChunk
from canary_framework import cocoa


@cocoa(deps=[Database])
class DocChunkRepository:
    database: Database

    async def add_many(self, session: AsyncSession, chunks: list[DocChunk]) -> list[DocChunk]:
        session.add_all(chunks)
        await session.flush()
        return chunks

    async def list_by_doc(self, session: AsyncSession, doc_id: str) -> list[DocChunk]:
        stmt = (
            select(DocChunk).where(DocChunk.doc_id == doc_id).order_by(DocChunk.chunk_index)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def delete_by_doc(self, session: AsyncSession, doc_id: str) -> int:
        chunks = await self.list_by_doc(session, doc_id)
        for chunk in chunks:
            await session.delete(chunk)
        return len(chunks)

    async def delete_by_book(self, session: AsyncSession, book_id: str) -> int:
        stmt = select(DocChunk).where(DocChunk.book_id == book_id)
        chunks = list((await session.execute(stmt)).scalars().all())
        for chunk in chunks:
            await session.delete(chunk)
        return len(chunks)

    async def search(
        self,
        session: AsyncSession,
        query_vector: list[float],
        *,
        top_k: int = 5,
        book_id: str | None = None,
    ) -> list[tuple[DocChunk, float]]:
        """Return the ``top_k`` most similar passages as ``(chunk, similarity)``.

        Similarity is cosine in ``[-1, 1]``; higher is closer, on both backends.
        """
        if not query_vector:
            return []
        if self.database.dialect == "postgres":
            return await self._search_pgvector(session, query_vector, top_k, book_id)
        return await self._search_python(session, query_vector, top_k, book_id)

    async def _search_pgvector(
        self,
        session: AsyncSession,
        query_vector: list[float],
        top_k: int,
        book_id: str | None,
    ) -> list[tuple[DocChunk, float]]:
        distance = DocChunk.embedding.cosine_distance(query_vector).label("distance")
        stmt = select(DocChunk, distance).where(DocChunk.embedding.is_not(None))
        if book_id:
            stmt = stmt.where(DocChunk.book_id == book_id)
        stmt = stmt.order_by(distance).limit(top_k)
        rows = (await session.execute(stmt)).all()
        return [(row[0], 1.0 - float(row[1])) for row in rows]

    async def _search_python(
        self,
        session: AsyncSession,
        query_vector: list[float],
        top_k: int,
        book_id: str | None,
    ) -> list[tuple[DocChunk, float]]:
        stmt = select(DocChunk).where(DocChunk.embedding.is_not(None))
        if book_id:
            stmt = stmt.where(DocChunk.book_id == book_id)
        candidates = list((await session.execute(stmt)).scalars().all())
        scored = [(c, cosine(query_vector, c.embedding or [])) for c in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

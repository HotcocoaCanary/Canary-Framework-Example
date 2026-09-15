"""Corpus queries — the indexable texts behind retrieval."""

from __future__ import annotations

from canary_framework import Canary
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import LibraryDoc


class LibraryDocRepository(Canary):
    async def add(self, session: AsyncSession, doc: LibraryDoc) -> LibraryDoc:
        session.add(doc)
        await session.flush()
        return doc

    async def get(self, session: AsyncSession, doc_id: str) -> LibraryDoc | None:
        return await session.get(LibraryDoc, doc_id)

    async def get_many(self, session: AsyncSession, doc_ids: list[str]) -> list[LibraryDoc]:
        if not doc_ids:
            return []
        stmt = select(LibraryDoc).where(LibraryDoc.id.in_(doc_ids))
        return list((await session.execute(stmt)).scalars().all())

    async def list_by_book(self, session: AsyncSession, book_id: str) -> list[LibraryDoc]:
        stmt = select(LibraryDoc).where(LibraryDoc.book_id == book_id)
        return list((await session.execute(stmt)).scalars().all())

    async def search(
        self,
        session: AsyncSession,
        *,
        book_id: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[LibraryDoc], int]:
        conditions = []
        if book_id:
            conditions.append(LibraryDoc.book_id == book_id)
        if status:
            conditions.append(LibraryDoc.status == status)

        stmt = select(LibraryDoc)
        count_stmt = select(func.count()).select_from(LibraryDoc)
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(LibraryDoc.created_at.desc()).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete(self, session: AsyncSession, doc: LibraryDoc) -> None:
        await session.delete(doc)

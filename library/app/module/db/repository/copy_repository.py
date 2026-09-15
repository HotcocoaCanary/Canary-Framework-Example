"""Holdings queries — the physical copies that circulate."""

from __future__ import annotations

from canary_framework import Canary
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import BookCopy


class BookCopyRepository(Canary):
    async def add(self, session: AsyncSession, copy: BookCopy) -> BookCopy:
        session.add(copy)
        await session.flush()
        return copy

    async def get(self, session: AsyncSession, copy_id: str) -> BookCopy | None:
        return await session.get(BookCopy, copy_id)

    async def get_by_barcode(self, session: AsyncSession, barcode: str) -> BookCopy | None:
        stmt = select(BookCopy).where(BookCopy.barcode == barcode)
        return (await session.execute(stmt)).scalars().first()

    async def list_by_book(self, session: AsyncSession, book_id: str) -> list[BookCopy]:
        stmt = select(BookCopy).where(BookCopy.book_id == book_id).order_by(BookCopy.barcode)
        return list((await session.execute(stmt)).scalars().all())

    async def first_available(self, session: AsyncSession, book_id: str) -> BookCopy | None:
        stmt = (
            select(BookCopy)
            .where(BookCopy.book_id == book_id, BookCopy.status == "available")
            .order_by(BookCopy.barcode)
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    async def count_by_status(self, session: AsyncSession, book_id: str) -> dict[str, int]:
        stmt = (
            select(BookCopy.status, func.count())
            .where(BookCopy.book_id == book_id)
            .group_by(BookCopy.status)
        )
        return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}

    async def counts_for_books(
        self, session: AsyncSession, book_ids: list[str]
    ) -> dict[str, dict[str, int]]:
        """Holdings counts for many titles at once — avoids an N+1 on list pages."""
        if not book_ids:
            return {}
        stmt = (
            select(BookCopy.book_id, BookCopy.status, func.count())
            .where(BookCopy.book_id.in_(book_ids))
            .group_by(BookCopy.book_id, BookCopy.status)
        )
        result: dict[str, dict[str, int]] = {}
        for book_id, status, count in (await session.execute(stmt)).all():
            result.setdefault(book_id, {})[status] = int(count)
        return result

    async def delete_by_book(self, session: AsyncSession, book_id: str) -> int:
        copies = await self.list_by_book(session, book_id)
        for copy in copies:
            await session.delete(copy)
        return len(copies)

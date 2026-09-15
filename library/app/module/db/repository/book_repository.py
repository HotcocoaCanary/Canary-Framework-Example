"""Catalogue queries — bibliographic records."""

from __future__ import annotations

from canary_framework import Canary
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import Book


class BookRepository(Canary):
    async def add(self, session: AsyncSession, book: Book) -> Book:
        session.add(book)
        await session.flush()
        return book

    async def get(self, session: AsyncSession, book_id: str) -> Book | None:
        return await session.get(Book, book_id)

    async def get_by_isbn(self, session: AsyncSession, isbn: str) -> Book | None:
        stmt = select(Book).where(Book.isbn == isbn)
        return (await session.execute(stmt)).scalars().first()

    async def get_many(self, session: AsyncSession, book_ids: list[str]) -> list[Book]:
        if not book_ids:
            return []
        stmt = select(Book).where(Book.id.in_(book_ids))
        return list((await session.execute(stmt)).scalars().all())

    async def search(
        self,
        session: AsyncSession,
        *,
        keyword: str | None = None,
        category: str | None = None,
        author: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Book], int]:
        """Keyword search over title / author / ISBN, with optional facets."""
        conditions = []
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
            )
        if category:
            conditions.append(Book.category == category)
        if author:
            conditions.append(Book.author.ilike(f"%{author}%"))

        stmt = select(Book)
        count_stmt = select(func.count()).select_from(Book)
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Book.created_at.desc()).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete(self, session: AsyncSession, book: Book) -> None:
        await session.delete(book)

    async def categories(self, session: AsyncSession) -> list[tuple[str, int]]:
        """``(category, book_count)`` — the shelf breakdown."""
        stmt = select(Book.category, func.count()).group_by(Book.category).order_by(Book.category)
        return [(row[0], int(row[1])) for row in (await session.execute(stmt)).all()]

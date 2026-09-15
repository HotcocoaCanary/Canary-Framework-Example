"""Reader queries — library card holders."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import Reader
from canary_framework import cocoa


@cocoa
class ReaderRepository:
    async def add(self, session: AsyncSession, reader: Reader) -> Reader:
        session.add(reader)
        await session.flush()
        return reader

    async def get(self, session: AsyncSession, reader_id: str) -> Reader | None:
        return await session.get(Reader, reader_id)

    async def get_by_card(self, session: AsyncSession, card_no: str) -> Reader | None:
        stmt = select(Reader).where(Reader.card_no == card_no)
        return (await session.execute(stmt)).scalars().first()

    async def search(
        self,
        session: AsyncSession,
        *,
        keyword: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Reader], int]:
        conditions = []
        if keyword:
            like = f"%{keyword}%"
            conditions.append(or_(Reader.name.ilike(like), Reader.card_no.ilike(like)))
        if status:
            conditions.append(Reader.status == status)

        stmt = select(Reader)
        count_stmt = select(func.count()).select_from(Reader)
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Reader.created_at.desc()).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete(self, session: AsyncSession, reader: Reader) -> None:
        await session.delete(reader)

"""Circulation queries — loans and their overdue state."""

from __future__ import annotations

from datetime import datetime

from canary_framework import Canary
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import Loan


class LoanRepository(Canary):
    async def add(self, session: AsyncSession, loan: Loan) -> Loan:
        session.add(loan)
        await session.flush()
        return loan

    async def get(self, session: AsyncSession, loan_id: str) -> Loan | None:
        return await session.get(Loan, loan_id)

    async def active_for_copy(self, session: AsyncSession, copy_id: str) -> Loan | None:
        stmt = select(Loan).where(Loan.copy_id == copy_id, Loan.status == "active")
        return (await session.execute(stmt)).scalars().first()

    async def active_for_reader(self, session: AsyncSession, reader_id: str) -> list[Loan]:
        stmt = (
            select(Loan)
            .where(Loan.reader_id == reader_id, Loan.status == "active")
            .order_by(Loan.due_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def count_active_for_reader(self, session: AsyncSession, reader_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Loan)
            .where(Loan.reader_id == reader_id, Loan.status == "active")
        )
        return int((await session.execute(stmt)).scalar_one())

    async def count_overdue_for_reader(
        self, session: AsyncSession, reader_id: str, now: datetime
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Loan)
            .where(Loan.reader_id == reader_id, Loan.status == "active", Loan.due_at < now)
        )
        return int((await session.execute(stmt)).scalar_one())

    async def history_for_reader(
        self, session: AsyncSession, reader_id: str, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Loan], int]:
        base = select(Loan).where(Loan.reader_id == reader_id)
        total = (
            await session.execute(
                select(func.count()).select_from(Loan).where(Loan.reader_id == reader_id)
            )
        ).scalar_one()
        stmt = base.order_by(Loan.borrowed_at.desc()).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def list_overdue(
        self, session: AsyncSession, now: datetime, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Loan], int]:
        condition = (Loan.status == "active", Loan.due_at < now)
        total = (
            await session.execute(select(func.count()).select_from(Loan).where(*condition))
        ).scalar_one()
        stmt = select(Loan).where(*condition).order_by(Loan.due_at).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete_by_book(self, session: AsyncSession, book_id: str) -> int:
        stmt = select(Loan).where(Loan.book_id == book_id)
        loans = list((await session.execute(stmt)).scalars().all())
        for loan in loans:
            await session.delete(loan)
        return len(loans)

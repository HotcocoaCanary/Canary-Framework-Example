"""Hold-queue queries — reservations against a title."""

from __future__ import annotations

from canary_framework import Canary
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import Reservation


class ReservationRepository(Canary):
    async def add(self, session: AsyncSession, reservation: Reservation) -> Reservation:
        session.add(reservation)
        await session.flush()
        return reservation

    async def get(self, session: AsyncSession, reservation_id: str) -> Reservation | None:
        return await session.get(Reservation, reservation_id)

    async def next_waiting(self, session: AsyncSession, book_id: str) -> Reservation | None:
        """The head of the queue — reservations are served first-come-first-served."""
        stmt = (
            select(Reservation)
            .where(Reservation.book_id == book_id, Reservation.status == "waiting")
            .order_by(Reservation.created_at)
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    async def find_open(
        self, session: AsyncSession, book_id: str, reader_id: str
    ) -> Reservation | None:
        stmt = select(Reservation).where(
            Reservation.book_id == book_id,
            Reservation.reader_id == reader_id,
            Reservation.status.in_(["waiting", "ready"]),
        )
        return (await session.execute(stmt)).scalars().first()

    async def count_open(self, session: AsyncSession, book_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Reservation)
            .where(Reservation.book_id == book_id, Reservation.status.in_(["waiting", "ready"]))
        )
        return int((await session.execute(stmt)).scalar_one())

    async def list_for_reader(
        self, session: AsyncSession, reader_id: str, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[Reservation], int]:
        condition = Reservation.reader_id == reader_id
        total = (
            await session.execute(select(func.count()).select_from(Reservation).where(condition))
        ).scalar_one()
        stmt = (
            select(Reservation)
            .where(condition)
            .order_by(Reservation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete_by_book(self, session: AsyncSession, book_id: str) -> int:
        stmt = select(Reservation).where(Reservation.book_id == book_id)
        rows = list((await session.execute(stmt)).scalars().all())
        for row in rows:
            await session.delete(row)
        return len(rows)

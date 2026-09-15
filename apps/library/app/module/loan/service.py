"""Circulation rules — borrow, return, renew and the hold queue.

Every operation runs inside one unit of work, because each of them touches
several aggregates at once: borrowing writes a ``Loan`` *and* flips the
``BookCopy`` status, returning also credits a fine to the ``Reader`` and may
promote the next ``Reservation``.  A partial write here would strand a copy in
``on_loan`` with no loan record behind it.
"""

from __future__ import annotations

from datetime import timedelta

from app.common.errors import ConflictError, NotFoundError, ValidationError
from app.common.ids import new_id
from app.common.response import PageResult, offset_of
from app.infra.db import Database
from app.module.db.models import Book, BookCopy, Loan, Reader, Reservation, utcnow
from app.module.db.repository.book_repository import BookRepository
from app.module.db.repository.copy_repository import BookCopyRepository
from app.module.db.repository.loan_repository import LoanRepository
from app.module.db.repository.reader_repository import ReaderRepository
from app.module.db.repository.reservation_repository import ReservationRepository
from app.module.loan.schema import (
    BorrowRequest,
    LoanResponse,
    ReservationResponse,
    ReserveRequest,
    ReturnReceipt,
    ReturnRequest,
)
from canary_framework import cocoa
from config import AppConfig


@cocoa(
    deps=[
        AppConfig,
        Database,
        BookRepository,
        BookCopyRepository,
        ReaderRepository,
        LoanRepository,
        ReservationRepository,
    ]
)
class CirculationService:
    app_config: AppConfig
    database: Database
    book_repository: BookRepository
    book_copy_repository: BookCopyRepository
    reader_repository: ReaderRepository
    loan_repository: LoanRepository
    reservation_repository: ReservationRepository

    # -- 借书 ----------------------------------------------------------
    async def borrow(self, request: BorrowRequest) -> LoanResponse:
        if not (request.book_id or request.copy_id or request.barcode):
            raise ValidationError("book_id / copy_id / barcode 至少提供一个")
        async with self.database.begin() as session:
            reader = await self._require_reader(session, request.reader_id)
            await self._assert_borrowable(session, reader)

            copy = await self._resolve_copy_for_borrow(session, request, reader)
            book = await self.book_repository.get(session, copy.book_id)
            if book is None:
                raise NotFoundError(f"书目 {copy.book_id} 不存在")

            now = utcnow()
            loan = Loan(
                id=new_id("ln"),
                copy_id=copy.id,
                book_id=copy.book_id,
                reader_id=reader.id,
                borrowed_at=now,
                due_at=now + timedelta(days=self.app_config.loan_days(reader.level)),
                status="active",
            )
            await self.loan_repository.add(session, loan)

            copy.status = "on_loan"
            copy.updated_at = now
            session.add(copy)

            # 借走的正是为自己留存的那一册 → 预约兑现
            held = await self.reservation_repository.find_open(session, book.id, reader.id)
            if held is not None and held.status == "ready" and held.copy_id == copy.id:
                held.status = "fulfilled"
                session.add(held)

            return _to_loan(loan, book, copy, now)

    # -- 还书 ----------------------------------------------------------
    async def return_copy(self, request: ReturnRequest) -> ReturnReceipt:
        if not (request.copy_id or request.barcode):
            raise ValidationError("copy_id / barcode 至少提供一个")
        async with self.database.begin() as session:
            copy = await self._resolve_copy(session, request.copy_id, request.barcode)
            loan = await self.loan_repository.active_for_copy(session, copy.id)
            if loan is None:
                raise ConflictError(f"副本 {copy.barcode} 当前没有在借记录")

            now = utcnow()
            overdue_days = _overdue_days(loan.due_at, now)
            fine = overdue_days * self.app_config.fine_cents_per_overdue_day

            loan.returned_at = now
            loan.status = "returned"
            loan.fine_cents = fine
            session.add(loan)

            reader = await self.reader_repository.get(session, loan.reader_id)
            if reader is not None and fine:
                reader.fine_balance_cents += fine
                reader.updated_at = now
                session.add(reader)

            promoted = await self._release_or_hold(session, copy, now)
            book = await self.book_repository.get(session, loan.book_id)

            return ReturnReceipt(
                loan=_to_loan(loan, book, copy, now),
                fine_cents=fine,
                reader_fine_balance_cents=reader.fine_balance_cents if reader else 0,
                next_reservation_ready=promoted,
            )

    # -- 续借 ----------------------------------------------------------
    async def renew(self, loan_id: str) -> LoanResponse:
        async with self.database.begin() as session:
            loan = await self.loan_repository.get(session, loan_id)
            if loan is None:
                raise NotFoundError(f"借阅记录 {loan_id} 不存在")
            if loan.status != "active":
                raise ConflictError("该借阅已结束，无法续借")

            now = utcnow()
            if loan.due_at < now:
                raise ConflictError("已逾期，请先归还并缴清罚金")
            if loan.renew_count >= self.app_config.max_renews:
                raise ConflictError(f"续借次数已达上限（{self.app_config.max_renews} 次）")
            if await self.reservation_repository.count_open(session, loan.book_id):
                raise ConflictError("该书已有读者预约，无法续借")

            reader = await self.reader_repository.get(session, loan.reader_id)
            level = reader.level if reader else "normal"
            loan.due_at = loan.due_at + timedelta(days=self.app_config.loan_days(level))
            loan.renew_count += 1
            session.add(loan)

            book = await self.book_repository.get(session, loan.book_id)
            copy = await self.book_copy_repository.get(session, loan.copy_id)
            return _to_loan(loan, book, copy, now)

    # -- 查询 ----------------------------------------------------------
    async def get_loan(self, loan_id: str) -> LoanResponse:
        async with self.database.read() as session:
            loan = await self.loan_repository.get(session, loan_id)
            if loan is None:
                raise NotFoundError(f"借阅记录 {loan_id} 不存在")
            book = await self.book_repository.get(session, loan.book_id)
            copy = await self.book_copy_repository.get(session, loan.copy_id)
            return _to_loan(loan, book, copy, utcnow())

    async def reader_loans(
        self, reader_id: str, *, page: int, size: int
    ) -> PageResult[LoanResponse]:
        async with self.database.read() as session:
            reader = await self._require_reader(session, reader_id)
            loans, total = await self.loan_repository.history_for_reader(
                session, reader.id, offset=offset_of(page, size), limit=size
            )
            return PageResult.of(await self._decorate(session, loans), total, page, size)

    async def overdue_loans(self, *, page: int, size: int) -> PageResult[LoanResponse]:
        async with self.database.read() as session:
            loans, total = await self.loan_repository.list_overdue(
                session, utcnow(), offset=offset_of(page, size), limit=size
            )
            return PageResult.of(await self._decorate(session, loans), total, page, size)

    # -- 预约 ----------------------------------------------------------
    async def reserve(self, request: ReserveRequest) -> ReservationResponse:
        async with self.database.begin() as session:
            reader = await self._require_reader(session, request.reader_id)
            if reader.status != "active":
                raise ConflictError("读者账号已停用，无法预约")

            book = await self.book_repository.get(session, request.book_id)
            if book is None:
                raise NotFoundError(f"书目 {request.book_id} 不存在")

            if await self.reservation_repository.find_open(session, book.id, reader.id):
                raise ConflictError("已有进行中的预约，请勿重复提交")

            counts = await self.book_copy_repository.count_by_status(session, book.id)
            if counts.get("available", 0):
                raise ConflictError("该书当前有可借副本，请直接借阅")
            if not sum(counts.values()):
                raise ConflictError("该书暂无馆藏，无法预约")

            reservation = Reservation(
                id=new_id("rs"),
                book_id=book.id,
                reader_id=reader.id,
                status="waiting",
            )
            await self.reservation_repository.add(session, reservation)
            position = await self.reservation_repository.count_open(session, book.id)
            return _to_reservation(reservation, book, position)

    async def cancel_reservation(self, reservation_id: str) -> str:
        async with self.database.begin() as session:
            reservation = await self.reservation_repository.get(session, reservation_id)
            if reservation is None:
                raise NotFoundError(f"预约 {reservation_id} 不存在")
            if reservation.status not in ("waiting", "ready"):
                raise ConflictError(f"预约已处于 {reservation.status} 状态，无法取消")

            was_ready_copy = reservation.copy_id if reservation.status == "ready" else None
            reservation.status = "cancelled"
            session.add(reservation)

            if was_ready_copy:
                copy = await self.book_copy_repository.get(session, was_ready_copy)
                if copy is not None and copy.status == "reserved":
                    await self._release_or_hold(session, copy, utcnow())
            return f"预约 {reservation_id} 已取消"

    async def reader_reservations(
        self, reader_id: str, *, page: int, size: int
    ) -> PageResult[ReservationResponse]:
        async with self.database.read() as session:
            reader = await self._require_reader(session, reader_id)
            rows, total = await self.reservation_repository.list_for_reader(
                session, reader.id, offset=offset_of(page, size), limit=size
            )
            books = {
                b.id: b
                for b in await self.book_repository.get_many(session, [r.book_id for r in rows])
            }
            records = [_to_reservation(r, books.get(r.book_id), None) for r in rows]
            return PageResult.of(records, total, page, size)

    # -- internals -----------------------------------------------------
    async def _require_reader(self, session, reader_id: str) -> Reader:
        reader = await self.reader_repository.get(session, reader_id)
        if reader is None:
            reader = await self.reader_repository.get_by_card(session, reader_id)
        if reader is None:
            raise NotFoundError(f"读者 {reader_id} 不存在")
        return reader

    async def _assert_borrowable(self, session, reader: Reader) -> None:
        if reader.status != "active":
            raise ConflictError("读者账号已停用，无法借阅")
        overdue = await self.loan_repository.count_overdue_for_reader(session, reader.id, utcnow())
        if overdue:
            raise ConflictError(f"有 {overdue} 册逾期未还，请先归还")
        if reader.fine_balance_cents >= self.app_config.max_fine_cents_before_block:
            raise ConflictError(
                f"欠款 {reader.fine_balance_cents} 分已达停借线，请先缴清罚金"
            )
        active = await self.loan_repository.count_active_for_reader(session, reader.id)
        limit = self.app_config.max_loans(reader.level)
        if active >= limit:
            raise ConflictError(f"在借 {active} 册已达 {reader.level} 等级上限（{limit} 册）")

    async def _resolve_copy(
        self, session, copy_id: str | None, barcode: str | None
    ) -> BookCopy:
        copy = None
        if copy_id:
            copy = await self.book_copy_repository.get(session, copy_id)
        elif barcode:
            copy = await self.book_copy_repository.get_by_barcode(session, barcode)
        if copy is None:
            raise NotFoundError(f"馆藏副本 {copy_id or barcode} 不存在")
        return copy

    async def _resolve_copy_for_borrow(
        self, session, request: BorrowRequest, reader: Reader
    ) -> BookCopy:
        if request.copy_id or request.barcode:
            copy = await self._resolve_copy(session, request.copy_id, request.barcode)
            await self._assert_copy_lendable(session, copy, reader)
            return copy

        copy = await self.book_copy_repository.first_available(session, request.book_id)
        if copy is None:
            reserved = await self._reserved_copy_for(session, request.book_id, reader)
            if reserved is not None:
                return reserved
            counts = await self.book_copy_repository.count_by_status(session, request.book_id)
            if not sum(counts.values()):
                raise NotFoundError(f"书目 {request.book_id} 暂无馆藏")
            raise ConflictError("该书全部副本已借出，可提交预约")
        return copy

    async def _assert_copy_lendable(self, session, copy: BookCopy, reader: Reader) -> None:
        if copy.status == "available":
            return
        if copy.status == "reserved":
            held = await self.reservation_repository.find_open(session, copy.book_id, reader.id)
            if held is not None and held.status == "ready" and held.copy_id == copy.id:
                return
            raise ConflictError("该副本已为其他读者预留")
        if copy.status == "on_loan":
            raise ConflictError("该副本已借出")
        raise ConflictError(f"该副本当前状态为 {copy.status}，不可外借")

    async def _reserved_copy_for(
        self, session, book_id: str, reader: Reader
    ) -> BookCopy | None:
        """The copy held for *reader* under a ``ready`` reservation, if any."""
        held = await self.reservation_repository.find_open(session, book_id, reader.id)
        if held is None or held.status != "ready" or not held.copy_id:
            return None
        return await self.book_copy_repository.get(session, held.copy_id)

    async def _release_or_hold(self, session, copy: BookCopy, now) -> bool:
        """Shelve a returned copy — unless someone is waiting for that title.

        Returns ``True`` when the copy was put on hold for the next reader.
        """
        waiting = await self.reservation_repository.next_waiting(session, copy.book_id)
        if waiting is None:
            copy.status = "available"
            copy.updated_at = now
            session.add(copy)
            return False

        waiting.status = "ready"
        waiting.copy_id = copy.id
        waiting.ready_at = now
        waiting.expires_at = now + timedelta(hours=self.app_config.reservation_hold_hours)
        session.add(waiting)

        copy.status = "reserved"
        copy.updated_at = now
        session.add(copy)
        return True

    async def _decorate(self, session, loans: list[Loan]) -> list[LoanResponse]:
        books = {
            b.id: b
            for b in await self.book_repository.get_many(session, [ln.book_id for ln in loans])
        }
        now = utcnow()
        records = []
        for loan in loans:
            copy = await self.book_copy_repository.get(session, loan.copy_id)
            records.append(_to_loan(loan, books.get(loan.book_id), copy, now))
        return records


def _overdue_days(due_at, now) -> int:
    """Whole days past the due date — a partial day is not yet a fine."""
    if now <= due_at:
        return 0
    return (now - due_at).days


def _to_loan(loan: Loan, book: Book | None, copy: BookCopy | None, now) -> LoanResponse:
    reference = loan.returned_at or now
    return LoanResponse(
        id=loan.id,
        copy_id=loan.copy_id,
        book_id=loan.book_id,
        book_title=book.title if book else None,
        barcode=copy.barcode if copy else None,
        reader_id=loan.reader_id,
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        renew_count=loan.renew_count,
        status=loan.status,
        fine_cents=loan.fine_cents,
        overdue_days=_overdue_days(loan.due_at, reference),
    )


def _to_reservation(
    reservation: Reservation, book: Book | None, position: int | None
) -> ReservationResponse:
    return ReservationResponse(
        id=reservation.id,
        book_id=reservation.book_id,
        book_title=book.title if book else None,
        reader_id=reservation.reader_id,
        status=reservation.status,
        queue_position=position if reservation.status == "waiting" else None,
        copy_id=reservation.copy_id,
        created_at=reservation.created_at,
        ready_at=reservation.ready_at,
        expires_at=reservation.expires_at,
    )

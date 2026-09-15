"""Reader rules — card holders, their standing, and their outstanding fines."""

from __future__ import annotations

import random

from canary_framework import Canary, dep

from app.common.errors import ConflictError, NotFoundError, ValidationError
from app.common.ids import new_id
from app.common.response import PageResult, offset_of
from app.infra.db import Database
from app.module.db.models import Reader, utcnow
from app.module.db.repository.loan_repository import LoanRepository
from app.module.db.repository.reader_repository import ReaderRepository
from app.module.reader.schema import (
    CreateReaderRequest,
    PayFineRequest,
    ReaderResponse,
    UpdateReaderRequest,
)
from config import AppConfig

_LEVELS = {"student", "normal", "vip", "staff"}
_STATUSES = {"active", "suspended"}


class ReaderService(Canary):
    config = dep(AppConfig)
    database = dep(Database)
    readers = dep(ReaderRepository)
    loans = dep(LoanRepository)

    async def create_reader(self, request: CreateReaderRequest) -> ReaderResponse:
        if request.level not in _LEVELS:
            raise ValidationError(f"未知的读者等级: {request.level}")
        async with self.database.begin() as session:
            card_no = request.card_no or self._generate_card_no()
            if await self.readers.get_by_card(session, card_no):
                raise ConflictError(f"借书证号 {card_no} 已存在")
            reader = Reader(
                id=new_id("rd"),
                card_no=card_no,
                name=request.name,
                email=request.email,
                phone=request.phone,
                level=request.level,
            )
            await self.readers.add(session, reader)
            return self._to_response(reader, 0, 0)

    async def get_reader(self, reader_id: str) -> ReaderResponse:
        async with self.database.read() as session:
            reader = await self.require_reader(session, reader_id)
            return await self._with_loan_counts(session, reader)

    async def search_readers(
        self, *, keyword: str | None, status: str | None, page: int, size: int
    ) -> PageResult[ReaderResponse]:
        async with self.database.read() as session:
            readers, total = await self.readers.search(
                session,
                keyword=keyword,
                status=status,
                offset=offset_of(page, size),
                limit=size,
            )
            records = [await self._with_loan_counts(session, r) for r in readers]
            return PageResult.of(records, total, page, size)

    async def update_reader(self, reader_id: str, request: UpdateReaderRequest) -> ReaderResponse:
        async with self.database.begin() as session:
            reader = await self.require_reader(session, reader_id)
            changes = request.model_dump(exclude_none=True)
            if not changes:
                raise ValidationError("没有需要更新的字段")
            if "level" in changes and changes["level"] not in _LEVELS:
                raise ValidationError(f"未知的读者等级: {changes['level']}")
            if "status" in changes and changes["status"] not in _STATUSES:
                raise ValidationError(f"未知的读者状态: {changes['status']}")
            for key, value in changes.items():
                setattr(reader, key, value)
            reader.updated_at = utcnow()
            session.add(reader)
            return await self._with_loan_counts(session, reader)

    async def delete_reader(self, reader_id: str) -> str:
        async with self.database.begin() as session:
            reader = await self.require_reader(session, reader_id)
            active = await self.loans.count_active_for_reader(session, reader_id)
            if active:
                raise ConflictError(f"读者仍有 {active} 册未归还，无法注销")
            if reader.fine_balance_cents:
                raise ConflictError("读者仍有未缴罚金，无法注销")
            await self.readers.delete(session, reader)
            return f"读者 {reader_id} 已注销"

    async def pay_fine(self, reader_id: str, request: PayFineRequest) -> ReaderResponse:
        async with self.database.begin() as session:
            reader = await self.require_reader(session, reader_id)
            if request.amount_cents > reader.fine_balance_cents:
                raise ValidationError(
                    f"缴纳金额超出欠款（欠 {reader.fine_balance_cents} 分）"
                )
            reader.fine_balance_cents -= request.amount_cents
            reader.updated_at = utcnow()
            session.add(reader)
            return await self._with_loan_counts(session, reader)

    # -- shared with the circulation service ---------------------------
    async def require_reader(self, session, reader_id: str) -> Reader:
        reader = await self.readers.get(session, reader_id)
        if reader is None:
            reader = await self.readers.get_by_card(session, reader_id)
        if reader is None:
            raise NotFoundError(f"读者 {reader_id} 不存在")
        return reader

    def _to_response(self, reader: Reader, active: int, overdue: int) -> ReaderResponse:
        return ReaderResponse(
            id=reader.id,
            card_no=reader.card_no,
            name=reader.name,
            email=reader.email,
            phone=reader.phone,
            level=reader.level,
            status=reader.status,
            fine_balance_cents=reader.fine_balance_cents,
            max_loans=self.config.max_loans(reader.level),
            active_loans=active,
            overdue_loans=overdue,
            created_at=reader.created_at,
            updated_at=reader.updated_at,
        )

    async def _with_loan_counts(self, session, reader: Reader) -> ReaderResponse:
        active = await self.loans.count_active_for_reader(session, reader.id)
        overdue = await self.loans.count_overdue_for_reader(
            session, reader.id, utcnow()
        )
        return self._to_response(reader, active, overdue)

    @staticmethod
    def _generate_card_no() -> str:
        return f"L{random.randint(10**9, 10**10 - 1)}"

"""``/api/circulation`` — the loan desk: borrow, return, renew, reserve."""

from __future__ import annotations

from canary_framework import dep
from canary_framework.web.asgi.app import Router, delete, get, post

from app.common.response import PageR, R
from app.module.loan.schema import (
    BorrowRequest,
    LoanResponse,
    ReservationResponse,
    ReserveRequest,
    ReturnReceipt,
    ReturnRequest,
)
from app.module.loan.service import CirculationService


class CirculationApi(Router, prefix="/circulation"):
    circulation = dep(CirculationService)

    @post("/borrow")
    async def borrow(self, body: BorrowRequest) -> R[LoanResponse]:
        return R.ok(await self.circulation.borrow(body))

    @post("/return")
    async def return_copy(self, body: ReturnRequest) -> R[ReturnReceipt]:
        return R.ok(await self.circulation.return_copy(body))

    @post("/loans/{loan_id}/renew")
    async def renew(self, loan_id: str) -> R[LoanResponse]:
        return R.ok(await self.circulation.renew(loan_id))

    @get("/loans/{loan_id}")
    async def get_loan(self, loan_id: str) -> R[LoanResponse]:
        return R.ok(await self.circulation.get_loan(loan_id))

    @get("/readers/{reader_id}/loans")
    async def reader_loans(
        self, reader_id: str, page: int = 1, size: int = 20
    ) -> PageR[LoanResponse]:
        return PageR.ok(await self.circulation.reader_loans(reader_id, page=page, size=size))

    @get("/overdue")
    async def overdue(self, page: int = 1, size: int = 20) -> PageR[LoanResponse]:
        return PageR.ok(await self.circulation.overdue_loans(page=page, size=size))

    @post("/reservations")
    async def reserve(self, body: ReserveRequest) -> R[ReservationResponse]:
        return R.ok(await self.circulation.reserve(body))

    @delete("/reservations/{reservation_id}")
    async def cancel_reservation(self, reservation_id: str) -> R[str]:
        return R.ok(await self.circulation.cancel_reservation(reservation_id))

    @get("/readers/{reader_id}/reservations")
    async def reader_reservations(
        self, reader_id: str, page: int = 1, size: int = 20
    ) -> PageR[ReservationResponse]:
        return PageR.ok(await self.circulation.reader_reservations(reader_id, page=page, size=size))

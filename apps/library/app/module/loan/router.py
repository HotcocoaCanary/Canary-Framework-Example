"""``/circulation`` — the loan desk: borrow, return, renew, reserve."""

from __future__ import annotations

from app.common.errors import ok
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
from canary_framework.web import delete, get, post, web_cocoa


@web_cocoa(prefix="/api/circulation", deps=[CirculationService], tags=["借还流通"])
class CirculationRouter:
    circulation_service: CirculationService

    @post("/borrow")
    async def borrow(self, body: BorrowRequest) -> R[LoanResponse]:
        return await ok(self.circulation_service.borrow(body))

    @post("/return")
    async def return_copy(self, body: ReturnRequest) -> R[ReturnReceipt]:
        return await ok(self.circulation_service.return_copy(body))

    @post("/loans/{loan_id}/renew")
    async def renew(self, loan_id: str) -> R[LoanResponse]:
        return await ok(self.circulation_service.renew(loan_id))

    @get("/loans/{loan_id}")
    async def get_loan(self, loan_id: str) -> R[LoanResponse]:
        return await ok(self.circulation_service.get_loan(loan_id))

    @get("/readers/{reader_id}/loans")
    async def reader_loans(self, reader_id: str, page: int = 1, size: int = 20) -> PageR[LoanResponse]:
        return await ok(
            self.circulation_service.reader_loans(reader_id, page=page, size=size),
            envelope=PageR,
        )

    @get("/overdue")
    async def overdue(self, page: int = 1, size: int = 20) -> PageR[LoanResponse]:
        return await ok(
            self.circulation_service.overdue_loans(page=page, size=size),
            envelope=PageR,
        )

    @post("/reservations")
    async def reserve(self, body: ReserveRequest) -> R[ReservationResponse]:
        return await ok(self.circulation_service.reserve(body))

    @delete("/reservations/{reservation_id}")
    async def cancel_reservation(self, reservation_id: str) -> R[str]:
        return await ok(self.circulation_service.cancel_reservation(reservation_id))

    @get("/readers/{reader_id}/reservations")
    async def reader_reservations(
        self, reader_id: str, page: int = 1, size: int = 20
    ) -> PageR[ReservationResponse]:
        return await ok(
            self.circulation_service.reader_reservations(reader_id, page=page, size=size),
            envelope=PageR,
        )

"""``/api/circulation`` — the loan desk: borrow, return, renew, reserve."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

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
from app.wiring import unit

router = APIRouter(prefix="/api/circulation", tags=["借还流通"])

Circulation = Annotated[CirculationService, unit(CirculationService)]


@router.post("/borrow")
async def borrow(body: BorrowRequest, circulation: Circulation) -> R[LoanResponse]:
    return R.ok(await circulation.borrow(body))


@router.post("/return")
async def return_copy(body: ReturnRequest, circulation: Circulation) -> R[ReturnReceipt]:
    return R.ok(await circulation.return_copy(body))


@router.post("/loans/{loan_id}/renew")
async def renew(loan_id: str, circulation: Circulation) -> R[LoanResponse]:
    return R.ok(await circulation.renew(loan_id))


@router.get("/loans/{loan_id}")
async def get_loan(loan_id: str, circulation: Circulation) -> R[LoanResponse]:
    return R.ok(await circulation.get_loan(loan_id))


@router.get("/readers/{reader_id}/loans")
async def reader_loans(
    reader_id: str, circulation: Circulation, page: int = 1, size: int = 20
) -> PageR[LoanResponse]:
    return PageR.ok(await circulation.reader_loans(reader_id, page=page, size=size))


@router.get("/overdue")
async def overdue(circulation: Circulation, page: int = 1, size: int = 20) -> PageR[LoanResponse]:
    return PageR.ok(await circulation.overdue_loans(page=page, size=size))


@router.post("/reservations")
async def reserve(body: ReserveRequest, circulation: Circulation) -> R[ReservationResponse]:
    return R.ok(await circulation.reserve(body))


@router.delete("/reservations/{reservation_id}")
async def cancel_reservation(reservation_id: str, circulation: Circulation) -> R[str]:
    return R.ok(await circulation.cancel_reservation(reservation_id))


@router.get("/readers/{reader_id}/reservations")
async def reader_reservations(
    reader_id: str, circulation: Circulation, page: int = 1, size: int = 20
) -> PageR[ReservationResponse]:
    return PageR.ok(await circulation.reader_reservations(reader_id, page=page, size=size))

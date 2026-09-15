"""``/api/readers`` — card holders and their standing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.common.response import PageR, R
from app.module.reader.schema import (
    CreateReaderRequest,
    PayFineRequest,
    ReaderResponse,
    UpdateReaderRequest,
)
from app.module.reader.service import ReaderService
from app.wiring import unit

router = APIRouter(prefix="/api/readers", tags=["读者"])

Readers = Annotated[ReaderService, unit(ReaderService)]


@router.post("/")
async def create_reader(body: CreateReaderRequest, readers: Readers) -> R[ReaderResponse]:
    return R.ok(await readers.create_reader(body))


@router.get("/")
async def search_readers(
    readers: Readers,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageR[ReaderResponse]:
    return PageR.ok(
        await readers.search_readers(keyword=keyword, status=status, page=page, size=size)
    )


@router.get("/{reader_id}")
async def get_reader(reader_id: str, readers: Readers) -> R[ReaderResponse]:
    return R.ok(await readers.get_reader(reader_id))


@router.patch("/{reader_id}")
async def update_reader(
    reader_id: str, body: UpdateReaderRequest, readers: Readers
) -> R[ReaderResponse]:
    return R.ok(await readers.update_reader(reader_id, body))


@router.delete("/{reader_id}")
async def delete_reader(reader_id: str, readers: Readers) -> R[str]:
    return R.ok(await readers.delete_reader(reader_id))


@router.post("/{reader_id}/fines/payment")
async def pay_fine(
    reader_id: str, body: PayFineRequest, readers: Readers
) -> R[ReaderResponse]:
    return R.ok(await readers.pay_fine(reader_id, body))

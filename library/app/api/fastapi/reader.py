"""``/api/readers`` — card holders and their standing."""

from __future__ import annotations

from canary_framework import dep
from canary_framework.asgi.fastapi import Router, delete, get, patch, post

from app.common.response import PageR, R
from app.module.reader.schema import (
    CreateReaderRequest,
    PayFineRequest,
    ReaderResponse,
    UpdateReaderRequest,
)
from app.module.reader.service import ReaderService


class ReaderApi(Router, prefix="/readers", tags=["读者"]):
    readers = dep(ReaderService)

    @post("/")
    async def create_reader(self, body: CreateReaderRequest) -> R[ReaderResponse]:
        return R.ok(await self.readers.create_reader(body))

    @get("/")
    async def search_readers(
        self, keyword: str | None = None, status: str | None = None, page: int = 1, size: int = 20
    ) -> PageR[ReaderResponse]:
        return PageR.ok(
            await self.readers.search_readers(keyword=keyword, status=status, page=page, size=size)
        )

    @get("/{reader_id}")
    async def get_reader(self, reader_id: str) -> R[ReaderResponse]:
        return R.ok(await self.readers.get_reader(reader_id))

    @patch("/{reader_id}")
    async def update_reader(self, reader_id: str, body: UpdateReaderRequest) -> R[ReaderResponse]:
        return R.ok(await self.readers.update_reader(reader_id, body))

    @delete("/{reader_id}")
    async def delete_reader(self, reader_id: str) -> R[str]:
        return R.ok(await self.readers.delete_reader(reader_id))

    @post("/{reader_id}/fines/payment")
    async def pay_fine(self, reader_id: str, body: PayFineRequest) -> R[ReaderResponse]:
        return R.ok(await self.readers.pay_fine(reader_id, body))

"""``/readers`` — card holders and their standing."""

from __future__ import annotations

from app.common.errors import ok
from app.common.response import PageR, R
from app.module.reader.schema import (
    CreateReaderRequest,
    PayFineRequest,
    ReaderResponse,
    UpdateReaderRequest,
)
from app.module.reader.service import ReaderService
from canary_framework.web import delete, get, patch, post, web_cocoa


@web_cocoa(prefix="/api/readers", deps=[ReaderService], tags=["读者"])
class ReaderRouter:
    reader_service: ReaderService

    @post("/")
    async def create_reader(self, body: CreateReaderRequest) -> R[ReaderResponse]:
        return await ok(self.reader_service.create_reader(body))

    @get("/")
    async def search_readers(
        self,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PageR[ReaderResponse]:
        return await ok(
            self.reader_service.search_readers(
                keyword=keyword, status=status, page=page, size=size
            ),
            envelope=PageR,
        )

    @get("/{reader_id}")
    async def get_reader(self, reader_id: str) -> R[ReaderResponse]:
        return await ok(self.reader_service.get_reader(reader_id))

    @patch("/{reader_id}")
    async def update_reader(self, reader_id: str, body: UpdateReaderRequest) -> R[ReaderResponse]:
        return await ok(self.reader_service.update_reader(reader_id, body))

    @delete("/{reader_id}")
    async def delete_reader(self, reader_id: str) -> R[str]:
        return await ok(self.reader_service.delete_reader(reader_id))

    @post("/{reader_id}/fines/payment")
    async def pay_fine(self, reader_id: str, body: PayFineRequest) -> R[ReaderResponse]:
        return await ok(self.reader_service.pay_fine(reader_id, body))

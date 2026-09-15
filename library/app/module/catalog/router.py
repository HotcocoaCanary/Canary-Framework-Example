"""``/catalog`` — the bibliographic catalogue and its physical holdings."""

from __future__ import annotations

from app.common.errors import ok
from app.common.response import PageR, R
from app.module.catalog.schema import (
    AddCopiesRequest,
    BookResponse,
    CategoryCount,
    CopyResponse,
    CreateBookRequest,
    UpdateBookRequest,
    UpdateCopyRequest,
)
from app.module.catalog.service import CatalogService
from canary_framework.web import delete, get, patch, post, web_cocoa


@web_cocoa(prefix="/api/catalog", deps=[CatalogService], tags=["书目与馆藏"])
class CatalogRouter:
    catalog_service: CatalogService

    @post("/books")
    async def create_book(self, body: CreateBookRequest) -> R[BookResponse]:
        return await ok(self.catalog_service.create_book(body))

    @get("/books")
    async def search_books(
        self,
        keyword: str | None = None,
        category: str | None = None,
        author: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PageR[BookResponse]:
        return await ok(
            self.catalog_service.search_books(
                keyword=keyword, category=category, author=author, page=page, size=size
            ),
            envelope=PageR,
        )

    @get("/books/{book_id}")
    async def get_book(self, book_id: str) -> R[BookResponse]:
        return await ok(self.catalog_service.get_book(book_id))

    @patch("/books/{book_id}")
    async def update_book(self, book_id: str, body: UpdateBookRequest) -> R[BookResponse]:
        return await ok(self.catalog_service.update_book(book_id, body))

    @delete("/books/{book_id}")
    async def delete_book(self, book_id: str) -> R[str]:
        return await ok(self.catalog_service.delete_book(book_id))

    @post("/books/{book_id}/copies")
    async def add_copies(self, book_id: str, body: AddCopiesRequest) -> R[list[CopyResponse]]:
        return await ok(self.catalog_service.add_copies(book_id, body))

    @get("/books/{book_id}/copies")
    async def list_copies(self, book_id: str) -> R[list[CopyResponse]]:
        return await ok(self.catalog_service.list_copies(book_id))

    @patch("/copies/{copy_id}")
    async def update_copy(self, copy_id: str, body: UpdateCopyRequest) -> R[CopyResponse]:
        return await ok(self.catalog_service.update_copy(copy_id, body))

    @get("/categories")
    async def categories(self) -> R[list[CategoryCount]]:
        return await ok(self.catalog_service.categories())

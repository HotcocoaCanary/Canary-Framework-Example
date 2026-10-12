"""``/api/catalog`` — the bibliographic catalogue and its physical holdings.

路由单元：带标记的方法是接口，需要的 service 写成 ``dep(CatalogService)``，接口方法
是绑定方法，直接用 ``self.catalog``。不经 HTTP 也能调：``await api.get_book(book_id)``。

**前缀逐层叠加。** 这里只写 ``/catalog``，``/api`` 来自依赖它的 ``Api``（``app/api.py``）。
上一版每个 router 自己写全 ``/api/catalog``；换成路由单元后挂在哪儿由谁依赖它决定。
"""

from __future__ import annotations

from canary_framework import dep
from canary_framework.asgi.fastapi import Router, delete, get, patch, post

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


class CatalogApi(Router, prefix="/catalog", tags=["书目与馆藏"]):
    catalog = dep(CatalogService)

    @post("/books")
    async def create_book(self, body: CreateBookRequest) -> R[BookResponse]:
        return R.ok(await self.catalog.create_book(body))

    @get("/books")
    async def search_books(
        self,
        keyword: str | None = None,
        category: str | None = None,
        author: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PageR[BookResponse]:
        return PageR.ok(
            await self.catalog.search_books(
                keyword=keyword, category=category, author=author, page=page, size=size
            )
        )

    @get("/books/{book_id}")
    async def get_book(self, book_id: str) -> R[BookResponse]:
        return R.ok(await self.catalog.get_book(book_id))

    @patch("/books/{book_id}")
    async def update_book(self, book_id: str, body: UpdateBookRequest) -> R[BookResponse]:
        return R.ok(await self.catalog.update_book(book_id, body))

    @delete("/books/{book_id}")
    async def delete_book(self, book_id: str) -> R[str]:
        return R.ok(await self.catalog.delete_book(book_id))

    @post("/books/{book_id}/copies")
    async def add_copies(self, book_id: str, body: AddCopiesRequest) -> R[list[CopyResponse]]:
        return R.ok(await self.catalog.add_copies(book_id, body))

    @get("/books/{book_id}/copies")
    async def list_copies(self, book_id: str) -> R[list[CopyResponse]]:
        return R.ok(await self.catalog.list_copies(book_id))

    @patch("/copies/{copy_id}")
    async def update_copy(self, copy_id: str, body: UpdateCopyRequest) -> R[CopyResponse]:
        return R.ok(await self.catalog.update_copy(copy_id, body))

    @get("/categories")
    async def categories(self) -> R[list[CategoryCount]]:
        return R.ok(await self.catalog.categories())

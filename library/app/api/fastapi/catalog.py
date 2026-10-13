"""``/api/catalog`` — the bibliographic catalogue and its physical holdings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.api.fastapi.bridge import use
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

router = APIRouter(prefix="/catalog", tags=["书目与馆藏"])

Catalog = Annotated[CatalogService, use(CatalogService)]


@router.post("/books")
async def create_book(body: CreateBookRequest, catalog: Catalog) -> R[BookResponse]:
    return R.ok(await catalog.create_book(body))


@router.get("/books")
async def search_books(
    catalog: Catalog,
    keyword: str | None = None,
    category: str | None = None,
    author: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageR[BookResponse]:
    return PageR.ok(
        await catalog.search_books(
            keyword=keyword, category=category, author=author, page=page, size=size
        )
    )


@router.get("/books/{book_id}")
async def get_book(book_id: str, catalog: Catalog) -> R[BookResponse]:
    return R.ok(await catalog.get_book(book_id))


@router.patch("/books/{book_id}")
async def update_book(book_id: str, body: UpdateBookRequest, catalog: Catalog) -> R[BookResponse]:
    return R.ok(await catalog.update_book(book_id, body))


@router.delete("/books/{book_id}")
async def delete_book(book_id: str, catalog: Catalog) -> R[str]:
    return R.ok(await catalog.delete_book(book_id))


@router.post("/books/{book_id}/copies")
async def add_copies(
    book_id: str, body: AddCopiesRequest, catalog: Catalog
) -> R[list[CopyResponse]]:
    return R.ok(await catalog.add_copies(book_id, body))


@router.get("/books/{book_id}/copies")
async def list_copies(book_id: str, catalog: Catalog) -> R[list[CopyResponse]]:
    return R.ok(await catalog.list_copies(book_id))


@router.patch("/copies/{copy_id}")
async def update_copy(copy_id: str, body: UpdateCopyRequest, catalog: Catalog) -> R[CopyResponse]:
    return R.ok(await catalog.update_copy(copy_id, body))


@router.get("/categories")
async def categories(catalog: Catalog) -> R[list[CategoryCount]]:
    return R.ok(await catalog.categories())

"""Catalogue rules — bibliographic records and the holdings attached to them.

The service owns the transaction: it opens one unit of work per operation and
hands the session to each repository, so adding a book and its copies either
both land or neither does.
"""

from __future__ import annotations

from app.common.errors import ConflictError, NotFoundError, ValidationError
from app.common.ids import new_id
from app.common.response import PageResult, offset_of
from app.infra.db import Database
from app.module.catalog.schema import (
    AddCopiesRequest,
    BookResponse,
    CategoryCount,
    CopyResponse,
    CreateBookRequest,
    HoldingsSummary,
    UpdateBookRequest,
    UpdateCopyRequest,
)
from app.module.db.models import Book, BookCopy, utcnow
from app.module.db.repository.book_repository import BookRepository
from app.module.db.repository.chunk_repository import DocChunkRepository
from app.module.db.repository.copy_repository import BookCopyRepository
from app.module.db.repository.doc_repository import LibraryDocRepository
from app.module.db.repository.loan_repository import LoanRepository
from app.module.db.repository.reservation_repository import ReservationRepository
from canary_framework import cocoa

_COPY_STATUSES = {"available", "on_loan", "reserved", "lost", "repairing", "withdrawn"}
_STAFF_SETTABLE = {"available", "lost", "repairing", "withdrawn"}


@cocoa(
    deps=[
        Database,
        BookRepository,
        BookCopyRepository,
        LoanRepository,
        ReservationRepository,
        LibraryDocRepository,
        DocChunkRepository,
    ]
)
class CatalogService:
    database: Database
    book_repository: BookRepository
    book_copy_repository: BookCopyRepository
    loan_repository: LoanRepository
    reservation_repository: ReservationRepository
    library_doc_repository: LibraryDocRepository
    doc_chunk_repository: DocChunkRepository

    # -- 书目 ----------------------------------------------------------
    async def create_book(self, request: CreateBookRequest) -> BookResponse:
        async with self.database.begin() as session:
            if request.isbn:
                existing = await self.book_repository.get_by_isbn(session, request.isbn)
                if existing:
                    raise ConflictError(f"ISBN {request.isbn} 已存在（书目 {existing.id}）")

            book = Book(
                id=new_id("bk"),
                isbn=request.isbn,
                title=request.title,
                subtitle=request.subtitle,
                author=request.author,
                publisher=request.publisher,
                published_year=request.published_year,
                category=request.category,
                language=request.language,
                summary=request.summary,
                tags=request.tags,
            )
            await self.book_repository.add(session, book)
            for _ in range(request.copies):
                await self._add_copy(session, book, request.location)
            counts = await self.book_copy_repository.count_by_status(session, book.id)
            return _to_book(book, counts, 0)

    async def get_book(self, book_id: str) -> BookResponse:
        async with self.database.read() as session:
            book = await self._require_book(session, book_id)
            counts = await self.book_copy_repository.count_by_status(session, book_id)
            holds = await self.reservation_repository.count_open(session, book_id)
            return _to_book(book, counts, holds)

    async def search_books(
        self,
        *,
        keyword: str | None,
        category: str | None,
        author: str | None,
        page: int,
        size: int,
    ) -> PageResult[BookResponse]:
        async with self.database.read() as session:
            books, total = await self.book_repository.search(
                session,
                keyword=keyword,
                category=category,
                author=author,
                offset=offset_of(page, size),
                limit=size,
            )
            counts = await self.book_copy_repository.counts_for_books(
                session, [b.id for b in books]
            )
            records = [_to_book(b, counts.get(b.id, {}), 0) for b in books]
            return PageResult.of(records, total, page, size)

    async def update_book(self, book_id: str, request: UpdateBookRequest) -> BookResponse:
        async with self.database.begin() as session:
            book = await self._require_book(session, book_id)
            changes = request.model_dump(exclude_none=True)
            if not changes:
                raise ValidationError("没有需要更新的字段")
            for key, value in changes.items():
                setattr(book, key, value)
            book.updated_at = utcnow()
            session.add(book)
            counts = await self.book_copy_repository.count_by_status(session, book_id)
            holds = await self.reservation_repository.count_open(session, book_id)
            return _to_book(book, counts, holds)

    async def delete_book(self, book_id: str) -> str:
        """Withdraw a title — refused while any copy is still out on loan."""
        async with self.database.begin() as session:
            book = await self._require_book(session, book_id)
            counts = await self.book_copy_repository.count_by_status(session, book_id)
            if counts.get("on_loan", 0):
                raise ConflictError(f"仍有 {counts['on_loan']} 册在借，无法删除书目")

            for doc in await self.library_doc_repository.list_by_book(session, book_id):
                await self.doc_chunk_repository.delete_by_doc(session, doc.id)
                await self.library_doc_repository.delete(session, doc)
            await self.doc_chunk_repository.delete_by_book(session, book_id)
            await self.reservation_repository.delete_by_book(session, book_id)
            await self.loan_repository.delete_by_book(session, book_id)
            await self.book_copy_repository.delete_by_book(session, book_id)
            await self.book_repository.delete(session, book)
            return f"书目 {book_id} 及其馆藏已注销"

    async def categories(self) -> list[CategoryCount]:
        async with self.database.read() as session:
            rows = await self.book_repository.categories(session)
            return [CategoryCount(category=name, books=count) for name, count in rows]

    # -- 馆藏副本 ------------------------------------------------------
    async def add_copies(self, book_id: str, request: AddCopiesRequest) -> list[CopyResponse]:
        async with self.database.begin() as session:
            book = await self._require_book(session, book_id)
            copies = [
                await self._add_copy(session, book, request.location)
                for _ in range(request.count)
            ]
            return [_to_copy(c) for c in copies]

    async def list_copies(self, book_id: str) -> list[CopyResponse]:
        async with self.database.read() as session:
            await self._require_book(session, book_id)
            copies = await self.book_copy_repository.list_by_book(session, book_id)
            return [_to_copy(c) for c in copies]

    async def update_copy(self, copy_id: str, request: UpdateCopyRequest) -> CopyResponse:
        async with self.database.begin() as session:
            copy = await self.book_copy_repository.get(session, copy_id)
            if copy is None:
                raise NotFoundError(f"馆藏副本 {copy_id} 不存在")
            if request.status is not None:
                if request.status not in _COPY_STATUSES:
                    raise ValidationError(f"未知的副本状态: {request.status}")
                if request.status not in _STAFF_SETTABLE:
                    raise ValidationError(
                        f"{request.status} 由借还流程维护，不能直接设置"
                    )
                if copy.status == "on_loan":
                    raise ConflictError("副本在借中，请先办理归还")
                copy.status = request.status
            if request.location is not None:
                copy.location = request.location
            copy.updated_at = utcnow()
            session.add(copy)
            return _to_copy(copy)

    # -- internals -----------------------------------------------------
    async def _add_copy(self, session, book: Book, location: str) -> BookCopy:
        copy = BookCopy(
            id=new_id("cp"),
            book_id=book.id,
            barcode=new_id("bc").replace("bc_", "B"),
            location=location,
        )
        return await self.book_copy_repository.add(session, copy)

    async def _require_book(self, session, book_id: str) -> Book:
        book = await self.book_repository.get(session, book_id)
        if book is None:
            raise NotFoundError(f"书目 {book_id} 不存在")
        return book


def _to_book(book: Book, counts: dict[str, int], reservations: int) -> BookResponse:
    total = sum(counts.values())
    available = counts.get("available", 0)
    on_loan = counts.get("on_loan", 0)
    return BookResponse(
        id=book.id,
        isbn=book.isbn,
        title=book.title,
        subtitle=book.subtitle,
        author=book.author,
        publisher=book.publisher,
        published_year=book.published_year,
        category=book.category,
        language=book.language,
        summary=book.summary,
        tags=book.tags,
        holdings=HoldingsSummary(
            total=total,
            available=available,
            on_loan=on_loan,
            unavailable=total - available - on_loan,
            reservations=reservations,
        ),
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


def _to_copy(copy: BookCopy) -> CopyResponse:
    return CopyResponse(
        id=copy.id,
        book_id=copy.book_id,
        barcode=copy.barcode,
        location=copy.location,
        status=copy.status,
        acquired_at=copy.acquired_at,
    )

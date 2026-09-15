"""``/api/rag`` — the retrieval corpus: index documents, search passages."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.common.response import PageR, R
from app.module.rag.schema import DocResponse, IndexTextRequest, SearchResponse
from app.module.rag.service import RagService
from app.wiring import unit

router = APIRouter(prefix="/api/rag", tags=["知识库"])

Rag = Annotated[RagService, unit(RagService)]


@router.post("/documents")
async def index_text(body: IndexTextRequest, rag: Rag) -> R[DocResponse]:
    return R.ok(await rag.index_text(body))


@router.get("/documents")
async def list_docs(
    rag: Rag,
    book_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageR[DocResponse]:
    return PageR.ok(await rag.list_docs(book_id=book_id, status=status, page=page, size=size))


@router.get("/documents/{doc_id}")
async def get_doc(doc_id: str, rag: Rag) -> R[DocResponse]:
    return R.ok(await rag.get_doc(doc_id))


@router.post("/documents/{doc_id}/reindex")
async def reindex(doc_id: str, rag: Rag) -> R[DocResponse]:
    return R.ok(await rag.reindex(doc_id))


@router.delete("/documents/{doc_id}")
async def delete_doc(doc_id: str, rag: Rag) -> R[str]:
    return R.ok(await rag.delete_doc(doc_id))


@router.post("/books/{book_id}/index")
async def index_book(book_id: str, rag: Rag) -> R[DocResponse]:
    return R.ok(await rag.index_book(book_id))


@router.get("/search")
async def search(
    q: str, rag: Rag, top_k: int | None = None, book_id: str | None = None
) -> R[SearchResponse]:
    passages = await rag.retrieve(q, top_k=top_k, book_id=book_id)
    return R.ok(SearchResponse(query=q, passages=passages))

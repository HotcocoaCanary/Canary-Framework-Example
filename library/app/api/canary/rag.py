"""``/api/rag`` — the retrieval corpus: index documents, search passages."""

from __future__ import annotations

from canary_framework import dep
from canary_framework.web.asgi.app import Router, delete, get, post

from app.common.response import PageR, R
from app.module.rag.schema import DocResponse, IndexTextRequest, SearchResponse
from app.module.rag.service import RagService


class RagApi(Router, prefix="/rag"):
    rag = dep(RagService)

    @post("/documents")
    async def index_text(self, body: IndexTextRequest) -> R[DocResponse]:
        return R.ok(await self.rag.index_text(body))

    @get("/documents")
    async def list_docs(
        self, book_id: str | None = None, status: str | None = None, page: int = 1, size: int = 20
    ) -> PageR[DocResponse]:
        return PageR.ok(
            await self.rag.list_docs(book_id=book_id, status=status, page=page, size=size)
        )

    @get("/documents/{doc_id}")
    async def get_doc(self, doc_id: str) -> R[DocResponse]:
        return R.ok(await self.rag.get_doc(doc_id))

    @post("/documents/{doc_id}/reindex")
    async def reindex(self, doc_id: str) -> R[DocResponse]:
        return R.ok(await self.rag.reindex(doc_id))

    @delete("/documents/{doc_id}")
    async def delete_doc(self, doc_id: str) -> R[str]:
        return R.ok(await self.rag.delete_doc(doc_id))

    @post("/books/{book_id}/index")
    async def index_book(self, book_id: str) -> R[DocResponse]:
        return R.ok(await self.rag.index_book(book_id))

    @get("/search")
    async def search(
        self, q: str, top_k: int | None = None, book_id: str | None = None
    ) -> R[SearchResponse]:
        passages = await self.rag.retrieve(q, top_k=top_k, book_id=book_id)
        return R.ok(SearchResponse(query=q, passages=passages))

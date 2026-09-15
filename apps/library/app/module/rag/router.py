"""``/rag`` — the retrieval corpus: index documents, search passages."""

from __future__ import annotations

from app.common.errors import ok
from app.common.response import PageR, R
from app.module.rag.schema import DocResponse, IndexTextRequest, SearchResponse
from app.module.rag.service import RagService
from canary_framework.web import delete, get, post, web_cocoa


@web_cocoa(prefix="/api/rag", deps=[RagService], tags=["知识库"])
class RagRouter:
    rag_service: RagService

    @post("/documents")
    async def index_text(self, body: IndexTextRequest) -> R[DocResponse]:
        return await ok(self.rag_service.index_text(body))

    @get("/documents")
    async def list_docs(
        self,
        book_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PageR[DocResponse]:
        return await ok(
            self.rag_service.list_docs(book_id=book_id, status=status, page=page, size=size),
            envelope=PageR,
        )

    @get("/documents/{doc_id}")
    async def get_doc(self, doc_id: str) -> R[DocResponse]:
        return await ok(self.rag_service.get_doc(doc_id))

    @post("/documents/{doc_id}/reindex")
    async def reindex(self, doc_id: str) -> R[DocResponse]:
        return await ok(self.rag_service.reindex(doc_id))

    @delete("/documents/{doc_id}")
    async def delete_doc(self, doc_id: str) -> R[str]:
        return await ok(self.rag_service.delete_doc(doc_id))

    @post("/books/{book_id}/index")
    async def index_book(self, book_id: str) -> R[DocResponse]:
        return await ok(self.rag_service.index_book(book_id))

    @get("/search")
    async def search(
        self, q: str, top_k: int | None = None, book_id: str | None = None
    ) -> R[SearchResponse]:
        return await ok(self._search(q, top_k, book_id))

    async def _search(self, q: str, top_k: int | None, book_id: str | None) -> SearchResponse:
        passages = await self.rag_service.retrieve(q, top_k=top_k, book_id=book_id)
        return SearchResponse(query=q, passages=passages)

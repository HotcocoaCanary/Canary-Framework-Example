"""Retrieval — indexing the corpus and finding the passages that answer a query.

Indexing is synchronous on purpose.  Canary 0.9 has no background-task facility
(see ``doc/bug/010-no-background-tasks.md``), so a fire-and-forget
``asyncio.create_task`` would run unsupervised, outlive the request with no way
to report failure, and race the ASGI shutdown.  The document therefore carries a
``status`` field, which is where a future queue would write its progress.
"""

from __future__ import annotations

from app.common.errors import NotFoundError, ValidationError
from app.common.ids import new_id
from app.common.response import PageResult, offset_of
from app.infra.ai import EmbeddingModel
from app.infra.db import Database
from app.module.db.models import Book, DocChunk, LibraryDoc, utcnow
from app.module.db.repository.book_repository import BookRepository
from app.module.db.repository.chunk_repository import DocChunkRepository
from app.module.db.repository.doc_repository import LibraryDocRepository
from app.module.rag.chunker import TextChunker
from app.module.rag.schema import DocResponse, IndexTextRequest, Passage
from canary_framework import cocoa
from config import AppConfig

_SOURCES = {"catalog", "fulltext", "policy", "upload"}


@cocoa(
    deps=[
        AppConfig,
        Database,
        EmbeddingModel,
        TextChunker,
        LibraryDocRepository,
        DocChunkRepository,
        BookRepository,
    ]
)
class RagService:
    app_config: AppConfig
    database: Database
    embedding_model: EmbeddingModel
    text_chunker: TextChunker
    library_doc_repository: LibraryDocRepository
    doc_chunk_repository: DocChunkRepository
    book_repository: BookRepository

    # -- 建索引 --------------------------------------------------------
    async def index_text(self, request: IndexTextRequest) -> DocResponse:
        if request.source not in _SOURCES:
            raise ValidationError(f"未知的文献来源: {request.source}")

        async with self.database.begin() as session:
            if request.book_id and await self.book_repository.get(session, request.book_id) is None:
                raise NotFoundError(f"书目 {request.book_id} 不存在")
            doc = LibraryDoc(
                id=new_id("doc"),
                book_id=request.book_id,
                title=request.title,
                source=request.source,
                text=request.text,
            )
            await self.library_doc_repository.add(session, doc)
            await self._embed_into(session, doc)
            return _to_doc(doc)

    async def index_book(self, book_id: str) -> DocResponse:
        """Index a title's own metadata so the assistant can answer about it.

        The catalogue card — title, author, publisher, category, blurb — is
        itself a retrievable document, which is what lets a question like
        「有没有讲分布式系统的书」 hit the catalogue rather than only full texts.
        """
        async with self.database.begin() as session:
            book = await self.book_repository.get(session, book_id)
            if book is None:
                raise NotFoundError(f"书目 {book_id} 不存在")

            for existing in await self.library_doc_repository.list_by_book(session, book_id):
                if existing.source == "catalog":
                    await self.doc_chunk_repository.delete_by_doc(session, existing.id)
                    await self.library_doc_repository.delete(session, existing)

            doc = LibraryDoc(
                id=new_id("doc"),
                book_id=book.id,
                title=f"馆藏书目：{book.title}",
                source="catalog",
                text=_catalog_card(book),
            )
            await self.library_doc_repository.add(session, doc)
            await self._embed_into(session, doc)
            return _to_doc(doc)

    async def reindex(self, doc_id: str) -> DocResponse:
        async with self.database.begin() as session:
            doc = await self._require_doc(session, doc_id)
            await self.doc_chunk_repository.delete_by_doc(session, doc.id)
            await self._embed_into(session, doc)
            return _to_doc(doc)

    async def delete_doc(self, doc_id: str) -> str:
        async with self.database.begin() as session:
            doc = await self._require_doc(session, doc_id)
            removed = await self.doc_chunk_repository.delete_by_doc(session, doc.id)
            await self.library_doc_repository.delete(session, doc)
            return f"文献 {doc_id} 已删除（连带 {removed} 个片段）"

    # -- 查询 ----------------------------------------------------------
    async def get_doc(self, doc_id: str) -> DocResponse:
        async with self.database.read() as session:
            return _to_doc(await self._require_doc(session, doc_id))

    async def list_docs(
        self, *, book_id: str | None, status: str | None, page: int, size: int
    ) -> PageResult[DocResponse]:
        async with self.database.read() as session:
            docs, total = await self.library_doc_repository.search(
                session,
                book_id=book_id,
                status=status,
                offset=offset_of(page, size),
                limit=size,
            )
            return PageResult.of([_to_doc(d) for d in docs], total, page, size)

    async def retrieve(
        self, query: str, *, top_k: int | None = None, book_id: str | None = None
    ) -> list[Passage]:
        """Embed the query and return the closest passages above the noise floor."""
        if not query.strip():
            raise ValidationError("检索内容不能为空")
        limit = top_k or self.app_config.retrieve_top_k

        async with self.database.read() as session:
            vector = await self.embedding_model.embed(query)
            hits = await self.doc_chunk_repository.search(
                session, vector, top_k=limit, book_id=book_id
            )
            hits = [(c, s) for c, s in hits if s >= self.app_config.min_similarity]
            if not hits:
                return []

            docs = {
                d.id: d
                for d in await self.library_doc_repository.get_many(
                    session, [c.doc_id for c, _ in hits]
                )
            }
            book_ids = [c.book_id for c, _ in hits if c.book_id]
            books = {
                b.id: b for b in await self.book_repository.get_many(session, book_ids)
            }
            return [
                Passage(
                    chunk_id=chunk.id,
                    doc_id=chunk.doc_id,
                    doc_title=docs[chunk.doc_id].title if chunk.doc_id in docs else None,
                    book_id=chunk.book_id,
                    book_title=books[chunk.book_id].title if chunk.book_id in books else None,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    score=round(score, 6),
                )
                for chunk, score in hits
            ]

    # -- internals -----------------------------------------------------
    async def _embed_into(self, session, doc: LibraryDoc) -> None:
        """Split, embed and store — the document's ``status`` records the outcome."""
        pieces = self.text_chunker.split(doc.text)
        if not pieces:
            doc.status = "failed"
            doc.error_msg = "正文切分后为空"
            doc.chunk_count = 0
            doc.updated_at = utcnow()
            session.add(doc)
            return

        vectors = await self.embedding_model.embed_many(pieces)
        chunks = [
            DocChunk(
                id=new_id("ck"),
                doc_id=doc.id,
                book_id=doc.book_id,
                chunk_index=index,
                content=piece,
                embedding=vector,
            )
            for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
        ]
        await self.doc_chunk_repository.add_many(session, chunks)

        doc.status = "indexed"
        doc.error_msg = None
        doc.chunk_count = len(chunks)
        doc.updated_at = utcnow()
        session.add(doc)

    async def _require_doc(self, session, doc_id: str) -> LibraryDoc:
        doc = await self.library_doc_repository.get(session, doc_id)
        if doc is None:
            raise NotFoundError(f"文献 {doc_id} 不存在")
        return doc


def _catalog_card(book: Book) -> str:
    lines = [
        f"书名：{book.title}",
        f"作者：{book.author}",
        f"分类：{book.category}",
    ]
    if book.subtitle:
        lines.append(f"副标题：{book.subtitle}")
    if book.publisher:
        lines.append(f"出版社：{book.publisher}")
    if book.published_year:
        lines.append(f"出版年份：{book.published_year}")
    if book.isbn:
        lines.append(f"ISBN：{book.isbn}")
    if book.tags:
        lines.append("标签：" + "、".join(book.tags))
    if book.summary:
        lines.append(f"内容简介：{book.summary}")
    return "\n".join(lines)


def _to_doc(doc: LibraryDoc) -> DocResponse:
    return DocResponse(
        id=doc.id,
        book_id=doc.book_id,
        title=doc.title,
        source=doc.source,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_msg=doc.error_msg,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )

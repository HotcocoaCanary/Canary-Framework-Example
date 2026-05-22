from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from app.module.db_module.models import KbChunk


class ChunkRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, chunk: KbChunk) -> KbChunk:
        self._session.add(chunk)
        await self._session.flush()
        return chunk

    async def batch_create(self, chunks: list[KbChunk]) -> list[KbChunk]:
        self._session.add_all(chunks)
        await self._session.flush()
        return chunks

    async def search(self, embedding: list[float], kb_ids: list[str], file_ids: Optional[list[str]] = None,
                     top_k: int = 5) -> list[KbChunk]:
        stmt = select(KbChunk).where(KbChunk.kb_id.in_(kb_ids))
        if file_ids:
            stmt = stmt.where(KbChunk.file_id.in_(file_ids))
        stmt = stmt.order_by(KbChunk.embedding.cosine_distance(embedding)).limit(top_k)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def delete_by_file_id(self, file_id: str) -> None:
        stmt = delete(KbChunk).where(KbChunk.file_id == file_id)
        await self._session.exec(stmt)
        await self._session.flush()

    async def delete_by_kb(self, kb_id: str) -> None:
        stmt = delete(KbChunk).where(KbChunk.kb_id == kb_id)
        await self._session.exec(stmt)
        await self._session.flush()

    async def get_by_file_id(self, file_id: str) -> list[KbChunk]:
        stmt = select(KbChunk).where(KbChunk.file_id == file_id).order_by(KbChunk.chunk_index)
        result = await self._session.exec(stmt)
        return list(result.all())

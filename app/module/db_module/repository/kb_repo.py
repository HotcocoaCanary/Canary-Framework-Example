from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.module.db_module.models import KnowledgeBase


class KbRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, kb: KnowledgeBase) -> KnowledgeBase:
        self._session.add(kb)
        await self._session.flush()
        return kb

    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_by_user(self, user_id: str, current: int = 1, size: int = 20) -> tuple[list[KnowledgeBase], int]:
        base_stmt = select(KnowledgeBase).where(KnowledgeBase.created_by == user_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(KnowledgeBase.updated_at.desc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        kb.updated_at = datetime.utcnow()
        self._session.add(kb)
        await self._session.flush()
        return kb

    async def delete(self, kb_id: str) -> None:
        kb = await self.get_by_id(kb_id)
        if kb:
            await self._session.delete(kb)
            await self._session.flush()

    async def list_public(self, keyword: Optional[str] = None, current: int = 1, size: int = 20) -> tuple[
        list[KnowledgeBase], int]:
        base_stmt = select(KnowledgeBase).where(KnowledgeBase.permission == "public")
        if keyword:
            base_stmt = base_stmt.where(KnowledgeBase.name.ilike(f"%{keyword}%"))
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(KnowledgeBase.updated_at.desc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def get_by_share_token(self, share_token: str) -> Optional[KnowledgeBase]:
        stmt = select(KnowledgeBase).where(KnowledgeBase.share_token == share_token)
        result = await self._session.exec(stmt)
        return result.one_or_none()

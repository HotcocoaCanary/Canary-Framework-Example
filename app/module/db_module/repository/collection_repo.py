from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, delete

from app.module.db_module.models import CollectionItem


class CollectionRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, item: CollectionItem) -> CollectionItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_by_id(self, item_id: str) -> Optional[CollectionItem]:
        stmt = select(CollectionItem).where(CollectionItem.id == item_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_by_user(self, user_id: str, current: int = 1, size: int = 20) -> tuple[list[CollectionItem], int]:
        base_stmt = select(CollectionItem).where(CollectionItem.user_id == user_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(CollectionItem.created_at.desc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def update(self, item: CollectionItem) -> CollectionItem:
        item.updated_at = datetime.utcnow()
        self._session.add(item)
        await self._session.flush()
        return item

    async def delete(self, item_id: str) -> None:
        item = await self.get_by_id(item_id)
        if item:
            await self._session.delete(item)
            await self._session.flush()

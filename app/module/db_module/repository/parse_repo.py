from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.module.db_module.models import ParseTask


class ParseRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, task: ParseTask) -> ParseTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_by_id(self, task_id: str) -> Optional[ParseTask]:
        stmt = select(ParseTask).where(ParseTask.id == task_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_by_kb(self, kb_id: str, current: int = 1, size: int = 20) -> tuple[list[ParseTask], int]:
        base_stmt = select(ParseTask).where(ParseTask.kb_id == kb_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(ParseTask.created_at.desc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

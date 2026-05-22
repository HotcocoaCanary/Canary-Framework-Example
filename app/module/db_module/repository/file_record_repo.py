from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.module.db_module.models import KbFileRecord


class FileRecordRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, record: KbFileRecord) -> KbFileRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_file_id(self, file_id: str) -> Optional[KbFileRecord]:
        stmt = select(KbFileRecord).where(KbFileRecord.file_id == file_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def get_by_parse_task(self, parse_task_id: str) -> list[KbFileRecord]:
        stmt = select(KbFileRecord).where(KbFileRecord.parse_task_id == parse_task_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def get_by_file_ids(self, file_ids: list[str]) -> list[KbFileRecord]:
        stmt = select(KbFileRecord).where(KbFileRecord.file_id.in_(file_ids))
        result = await self._session.exec(stmt)
        return list(result.all())

    async def update(self, record: KbFileRecord) -> KbFileRecord:
        record.updated_at = datetime.utcnow()
        self._session.add(record)
        await self._session.flush()
        return record

    async def delete_by_file_id(self, file_id: str) -> None:
        record = await self.get_by_file_id(file_id)
        if record:
            await self._session.delete(record)
            await self._session.flush()

    async def delete_by_file_ids(self, file_ids: list[str]) -> None:
        stmt = delete(KbFileRecord).where(KbFileRecord.file_id.in_(file_ids))
        await self._session.exec(stmt)
        await self._session.flush()

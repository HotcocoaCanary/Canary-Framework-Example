from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, delete

from app.module.db_module.models import KbFile


class FileRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, file: KbFile) -> KbFile:
        self._session.add(file)
        await self._session.flush()
        return file

    async def get_by_id(self, file_id: str) -> Optional[KbFile]:
        stmt = select(KbFile).where(KbFile.id == file_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def get_by_path(self, kb_id: str, parent_path: str, name: str) -> Optional[KbFile]:
        stmt = select(KbFile).where(
            KbFile.kb_id == kb_id,
            KbFile.parent_path == parent_path,
            KbFile.name == name,
        )
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_children(self, kb_id: str, parent_path: Optional[str], current: int = 1, size: int = 20) -> tuple[
        list[KbFile], int]:
        if parent_path is None:
            base_stmt = select(KbFile).where(KbFile.kb_id == kb_id, KbFile.parent_path == None)  # noqa: E711
        else:
            base_stmt = select(KbFile).where(KbFile.kb_id == kb_id, KbFile.parent_path == parent_path)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(KbFile.file_type.asc(), KbFile.name.asc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def update(self, file: KbFile) -> KbFile:
        file.updated_at = datetime.utcnow()
        self._session.add(file)
        await self._session.flush()
        return file

    async def delete_by_id(self, file_id: str) -> None:
        f = await self.get_by_id(file_id)
        if f:
            await self._session.delete(f)
            await self._session.flush()

    async def delete_by_kb(self, kb_id: str) -> None:
        stmt = delete(KbFile).where(KbFile.kb_id == kb_id)
        await self._session.exec(stmt)
        await self._session.flush()

    async def delete_by_parent_prefix(self, kb_id: str, parent_path_prefix: str) -> None:
        stmt = delete(KbFile).where(
            KbFile.kb_id == kb_id,
            (KbFile.parent_path == parent_path_prefix)
            | (KbFile.parent_path.startswith(parent_path_prefix + "/"))
        )
        await self._session.exec(stmt)
        await self._session.flush()

    async def delete_by_parent_and_name(self, kb_id: str, parent_path: str, name: str) -> None:
        f = await self.get_by_path(kb_id, parent_path, name)
        if f:
            await self._session.delete(f)
            await self._session.flush()

    async def get_unique_name(self, kb_id: str, parent_path: str, name: str) -> str:
        existing = await self.get_by_path(kb_id, parent_path, name)
        if not existing:
            return name
        counter = 1
        while True:
            new_name = f"{name}_{counter}"
            existing = await self.get_by_path(kb_id, parent_path, new_name)
            if not existing:
                return new_name
            counter += 1

    async def list_by_kb(self, kb_id: str) -> list[KbFile]:
        stmt = select(KbFile).where(KbFile.kb_id == kb_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def total_size_by_owner(self, user_id: str) -> int:
        stmt = select(func.coalesce(func.sum(KbFile.file_size), 0)).where(
            KbFile.file_type != None,  # noqa: E711
            KbFile.created_by == user_id
        )
        result = await self._session.exec(stmt)
        return result.one()

    async def get_by_ids(self, file_ids: list[str]) -> list[KbFile]:
        stmt = select(KbFile).where(KbFile.id.in_(file_ids))
        result = await self._session.exec(stmt)
        return list(result.all())

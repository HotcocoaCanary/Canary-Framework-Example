from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, delete

from app.module.db_module.models import KbNode


class NodeRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, node: KbNode) -> KbNode:
        self._session.add(node)
        await self._session.flush()
        return node

    async def get_by_id(self, node_id: str) -> Optional[KbNode]:
        stmt = select(KbNode).where(KbNode.id == node_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def get_by_path(self, kb_id: str, full_path: str) -> Optional[KbNode]:
        stmt = select(KbNode).where(KbNode.kb_id == kb_id, KbNode.full_path == full_path)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_children(self, kb_id: str, parent_path: Optional[str], current: int = 1, size: int = 20) -> tuple[
        list[KbNode], int]:
        if parent_path is None:
            base_stmt = select(KbNode).where(KbNode.kb_id == kb_id, KbNode.parent_path == None)  # noqa: E711
        else:
            base_stmt = select(KbNode).where(KbNode.kb_id == kb_id, KbNode.parent_path == parent_path)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(KbNode.node_type.asc(), KbNode.name.asc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def update(self, node: KbNode) -> KbNode:
        node.updated_at = datetime.utcnow()
        self._session.add(node)
        await self._session.flush()
        return node

    async def delete_by_id(self, node_id: str) -> None:
        node = await self.get_by_id(node_id)
        if node:
            await self._session.delete(node)
            await self._session.flush()

    async def delete_by_kb(self, kb_id: str) -> None:
        stmt = delete(KbNode).where(KbNode.kb_id == kb_id)
        await self._session.exec(stmt)
        await self._session.flush()

    async def delete_by_path_prefix(self, kb_id: str, full_path_prefix: str) -> None:
        stmt = delete(KbNode).where(
            KbNode.kb_id == kb_id,
            (KbNode.full_path == full_path_prefix) | (KbNode.full_path.startswith(full_path_prefix + "/"))
        )
        await self._session.exec(stmt)
        await self._session.flush()

    async def get_unique_name(self, kb_id: str, parent_path: Optional[str], name: str) -> str:
        existing = await self.get_by_path(kb_id, (parent_path or "") + "/" + name)
        if not existing:
            return name
        counter = 1
        while True:
            new_name = f"{name}_{counter}"
            existing = await self.get_by_path(kb_id, (parent_path or "") + "/" + new_name)
            if not existing:
                return new_name
            counter += 1

    async def list_by_kb(self, kb_id: str) -> list[KbNode]:
        stmt = select(KbNode).where(KbNode.kb_id == kb_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def total_size_by_owner(self, user_id: str) -> int:
        stmt = select(func.coalesce(func.sum(KbNode.size), 0)).where(
            KbNode.node_type != None,  # noqa: E711
            KbNode.created_by == user_id
        )
        result = await self._session.exec(stmt)
        return result.one()

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db_module.models import KbMember


class MemberRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, member: KbMember) -> KbMember:
        self._session.add(member)
        await self._session.flush()
        return member

    async def get(self, kb_id: str, user_id: str) -> Optional[KbMember]:
        stmt = select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_by_kb(self, kb_id: str) -> list[KbMember]:
        stmt = select(KbMember).where(KbMember.kb_id == kb_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def list_by_user(self, user_id: str) -> list[str]:
        stmt = select(KbMember.kb_id).where(KbMember.user_id == user_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def delete(self, kb_id: str, user_id: str) -> None:
        member = await self.get(kb_id, user_id)
        if member:
            await self._session.delete(member)
            await self._session.flush()

    async def delete_by_kb(self, kb_id: str) -> None:
        members = await self.list_by_kb(kb_id)
        for m in members:
            await self._session.delete(m)
        await self._session.flush()

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from src.module.db_module.models import Session


class SessionRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, sess: Session) -> Session:
        self._session.add(sess)
        await self._session.flush()
        return sess

    async def get_by_id(self, session_id: str) -> Optional[Session]:
        stmt = select(Session).where(Session.id == session_id)
        result = await self._session.exec(stmt)
        return result.one_or_none()

    async def list_by_user(self, user_id: str, current: int = 1, size: int = 20) -> tuple[list[Session], int]:
        base_stmt = select(Session).where(Session.user_id == user_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(Session.updated_at.desc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def update(self, sess: Session) -> Session:
        sess.updated_at = datetime.utcnow()
        self._session.add(sess)
        await self._session.flush()
        return sess

    async def delete(self, session_id: str) -> None:
        sess = await self.get_by_id(session_id)
        if sess:
            await self._session.delete(sess)
            await self._session.flush()

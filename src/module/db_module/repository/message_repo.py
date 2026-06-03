from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, delete

from src.module.db_module.models import Message


class MessageRepo:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, message: Message) -> Message:
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_by_session(self, session_id: str, current: int = 1, size: int = 50) -> tuple[list[Message], int]:
        base_stmt = select(Message).where(Message.session_id == session_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.exec(count_stmt)
        total = total_result.one()
        stmt = base_stmt.order_by(Message.created_at.asc()).offset((current - 1) * size).limit(size)
        result = await self._session.exec(stmt)
        records = list(result.all())
        return records, total

    async def get_history_content(self, session_id: str) -> list[Message]:
        stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        result = await self._session.exec(stmt)
        return list(result.all())

    async def delete_by_session(self, session_id: str) -> None:
        stmt = delete(Message).where(Message.session_id == session_id)
        await self._session.exec(stmt)
        await self._session.flush()

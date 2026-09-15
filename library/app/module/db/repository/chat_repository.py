"""Assistant-conversation queries."""

from __future__ import annotations

from canary_framework import Canary
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.module.db.models import ChatMessage, ChatSession


class ChatSessionRepository(Canary):
    async def add(self, session: AsyncSession, chat: ChatSession) -> ChatSession:
        session.add(chat)
        await session.flush()
        return chat

    async def get(self, session: AsyncSession, chat_id: str) -> ChatSession | None:
        return await session.get(ChatSession, chat_id)

    async def list_for_reader(
        self, session: AsyncSession, reader_id: str | None, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[ChatSession], int]:
        stmt = select(ChatSession)
        count_stmt = select(func.count()).select_from(ChatSession)
        if reader_id:
            stmt = stmt.where(ChatSession.reader_id == reader_id)
            count_stmt = count_stmt.where(ChatSession.reader_id == reader_id)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(ChatSession.updated_at.desc()).offset(offset).limit(limit)
        return list((await session.execute(stmt)).scalars().all()), int(total)

    async def delete(self, session: AsyncSession, chat: ChatSession) -> None:
        await session.delete(chat)


class ChatMessageRepository(Canary):
    async def add(self, session: AsyncSession, message: ChatMessage) -> ChatMessage:
        session.add(message)
        await session.flush()
        return message

    async def list_by_session(self, session: AsyncSession, session_id: str) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def delete_by_session(self, session: AsyncSession, session_id: str) -> int:
        messages = await self.list_by_session(session, session_id)
        for message in messages:
            await session.delete(message)
        return len(messages)

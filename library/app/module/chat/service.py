"""The librarian assistant — retrieval-augmented answers with citations.

The assistant never answers from the model's own memory: if retrieval comes back
empty the question is refused outright, without a model call.  That keeps the
answer auditable — every response either cites passages the library actually
holds, or says it has none.
"""

from __future__ import annotations

from canary_framework import Canary, dep

from app.common.errors import NotFoundError, ValidationError
from app.common.ids import new_id
from app.common.response import PageResult, offset_of
from app.infra.ai import NO_ANSWER, ChatModel
from app.infra.db import Database
from app.module.chat.schema import (
    AnswerResponse,
    AskRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
)
from app.module.db.models import ChatMessage, ChatSession, utcnow
from app.module.db.repository.chat_repository import (
    ChatMessageRepository,
    ChatSessionRepository,
)
from app.module.rag.schema import Passage
from app.module.rag.service import RagService

INSTRUCTION = (
    "你是图书馆的智能馆员助手。只能依据下面提供的馆藏资料回答读者问题，"
    "并在回答中说明依据的是哪本书或哪份资料。"
    "如果资料中没有答案，直接回答不知道，不要编造。"
)

_HISTORY_TURNS = 6


class AssistantService(Canary):
    database = dep(Database)
    rag = dep(RagService)
    model = dep(ChatModel)
    sessions = dep(ChatSessionRepository)
    messages = dep(ChatMessageRepository)

    # -- 会话 ----------------------------------------------------------
    async def create_session(self, request: CreateChatSessionRequest) -> ChatSessionResponse:
        async with self.database.begin() as session:
            chat = ChatSession(
                id=new_id("cs"), reader_id=request.reader_id, title=request.title
            )
            await self.sessions.add(session, chat)
            return _to_session(chat)

    async def list_sessions(
        self, *, reader_id: str | None, page: int, size: int
    ) -> PageResult[ChatSessionResponse]:
        async with self.database.read() as session:
            rows, total = await self.sessions.list_for_reader(
                session, reader_id, offset=offset_of(page, size), limit=size
            )
            return PageResult.of([_to_session(r) for r in rows], total, page, size)

    async def list_messages(self, session_id: str) -> list[ChatMessageResponse]:
        async with self.database.read() as session:
            await self._require_session(session, session_id)
            rows = await self.messages.list_by_session(session, session_id)
            return [_to_message(m) for m in rows]

    async def delete_session(self, session_id: str) -> str:
        async with self.database.begin() as session:
            chat = await self._require_session(session, session_id)
            removed = await self.messages.delete_by_session(session, session_id)
            await self.sessions.delete(session, chat)
            return f"会话 {session_id} 已删除（连带 {removed} 条消息）"

    # -- 问答 ----------------------------------------------------------
    async def ask(self, request: AskRequest, session_id: str | None = None) -> AnswerResponse:
        question = request.question.strip()
        if not question:
            raise ValidationError("问题不能为空")

        history: list[dict[str, str]] = []
        if session_id is not None:
            async with self.database.read() as session:
                await self._require_session(session, session_id)
                history = _as_history(
                    await self.messages.list_by_session(session, session_id)
                )

        passages = await self.rag.retrieve(
            question, top_k=request.top_k, book_id=request.book_id
        )
        answer = (
            NO_ANSWER
            if not passages
            else await self.model.complete(
                instruction=INSTRUCTION,
                context=[p.content for p in passages],
                history=history,
                question=question,
            )
        )

        if session_id is not None:
            await self._record_turn(session_id, question, answer, passages)

        return AnswerResponse(
            session_id=session_id,
            question=question,
            answer=answer,
            sources=passages,
            grounded=bool(passages),
        )

    # -- internals -----------------------------------------------------
    async def _record_turn(
        self, session_id: str, question: str, answer: str, passages: list[Passage]
    ) -> None:
        async with self.database.begin() as session:
            chat = await self._require_session(session, session_id)
            await self.messages.add(
                session,
                ChatMessage(
                    id=new_id("msg"), session_id=session_id, role="user", content=question
                ),
            )
            await self.messages.add(
                session,
                ChatMessage(
                    id=new_id("msg"),
                    session_id=session_id,
                    role="assistant",
                    content=answer,
                    sources=[p.model_dump(mode="json") for p in passages] or None,
                ),
            )
            chat.updated_at = utcnow()
            session.add(chat)

    async def _require_session(self, session, session_id: str) -> ChatSession:
        chat = await self.sessions.get(session, session_id)
        if chat is None:
            raise NotFoundError(f"会话 {session_id} 不存在")
        return chat


def _as_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """The last few turns, in the shape a chat API expects."""
    recent = messages[-_HISTORY_TURNS:]
    return [{"role": m.role, "content": m.content} for m in recent]


def _to_session(chat: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=chat.id,
        reader_id=chat.reader_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _to_message(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        sources=message.sources,
        created_at=message.created_at,
    )

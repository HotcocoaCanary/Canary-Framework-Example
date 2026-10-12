"""``/api/assistant`` — the librarian assistant's conversations."""

from __future__ import annotations

from canary_framework import dep
from canary_framework.asgi.web import Router, delete, get, post

from app.common.response import PageR, R
from app.module.chat.schema import (
    AnswerResponse,
    AskRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
)
from app.module.chat.service import AssistantService


class AssistantApi(Router, prefix="/assistant"):
    assistant = dep(AssistantService)

    @post("/ask")
    async def ask(self, body: AskRequest) -> R[AnswerResponse]:
        """One-shot question — no conversation is kept."""
        return R.ok(await self.assistant.ask(body))

    @post("/sessions")
    async def create_session(self, body: CreateChatSessionRequest) -> R[ChatSessionResponse]:
        return R.ok(await self.assistant.create_session(body))

    @get("/sessions")
    async def list_sessions(
        self, reader_id: str | None = None, page: int = 1, size: int = 20
    ) -> PageR[ChatSessionResponse]:
        return PageR.ok(
            await self.assistant.list_sessions(reader_id=reader_id, page=page, size=size)
        )

    @post("/sessions/{session_id}/ask")
    async def ask_in_session(self, session_id: str, body: AskRequest) -> R[AnswerResponse]:
        return R.ok(await self.assistant.ask(body, session_id=session_id))

    @get("/sessions/{session_id}/messages")
    async def list_messages(self, session_id: str) -> R[list[ChatMessageResponse]]:
        return R.ok(await self.assistant.list_messages(session_id))

    @delete("/sessions/{session_id}")
    async def delete_session(self, session_id: str) -> R[str]:
        return R.ok(await self.assistant.delete_session(session_id))

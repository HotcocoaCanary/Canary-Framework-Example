"""``/assistant`` — the librarian assistant's conversations."""

from __future__ import annotations

from app.common.errors import ok
from app.common.response import PageR, R
from app.module.chat.schema import (
    AnswerResponse,
    AskRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
)
from app.module.chat.service import AssistantService
from canary_framework.web import delete, get, post, web_cocoa


@web_cocoa(prefix="/api/assistant", deps=[AssistantService], tags=["智能助手"])
class AssistantRouter:
    assistant_service: AssistantService

    @post("/ask")
    async def ask(self, body: AskRequest) -> R[AnswerResponse]:
        """One-shot question — no conversation is kept."""
        return await ok(self.assistant_service.ask(body))

    @post("/sessions")
    async def create_session(self, body: CreateChatSessionRequest) -> R[ChatSessionResponse]:
        return await ok(self.assistant_service.create_session(body))

    @get("/sessions")
    async def list_sessions(
        self, reader_id: str | None = None, page: int = 1, size: int = 20
    ) -> PageR[ChatSessionResponse]:
        return await ok(
            self.assistant_service.list_sessions(reader_id=reader_id, page=page, size=size),
            envelope=PageR,
        )

    @post("/sessions/{session_id}/ask")
    async def ask_in_session(self, session_id: str, body: AskRequest) -> R[AnswerResponse]:
        return await ok(self.assistant_service.ask(body, session_id=session_id))

    @get("/sessions/{session_id}/messages")
    async def list_messages(self, session_id: str) -> R[list[ChatMessageResponse]]:
        return await ok(self.assistant_service.list_messages(session_id))

    @delete("/sessions/{session_id}")
    async def delete_session(self, session_id: str) -> R[str]:
        return await ok(self.assistant_service.delete_session(session_id))

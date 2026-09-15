"""``/api/assistant`` — the librarian assistant's conversations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.common.response import PageR, R
from app.module.chat.schema import (
    AnswerResponse,
    AskRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
)
from app.module.chat.service import AssistantService
from app.wiring import unit

router = APIRouter(prefix="/api/assistant", tags=["智能助手"])

Assistant = Annotated[AssistantService, unit(AssistantService)]


@router.post("/ask")
async def ask(body: AskRequest, assistant: Assistant) -> R[AnswerResponse]:
    """One-shot question — no conversation is kept."""
    return R.ok(await assistant.ask(body))


@router.post("/sessions")
async def create_session(
    body: CreateChatSessionRequest, assistant: Assistant
) -> R[ChatSessionResponse]:
    return R.ok(await assistant.create_session(body))


@router.get("/sessions")
async def list_sessions(
    assistant: Assistant, reader_id: str | None = None, page: int = 1, size: int = 20
) -> PageR[ChatSessionResponse]:
    return PageR.ok(await assistant.list_sessions(reader_id=reader_id, page=page, size=size))


@router.post("/sessions/{session_id}/ask")
async def ask_in_session(
    session_id: str, body: AskRequest, assistant: Assistant
) -> R[AnswerResponse]:
    return R.ok(await assistant.ask(body, session_id=session_id))


@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: str, assistant: Assistant) -> R[list[ChatMessageResponse]]:
    return R.ok(await assistant.list_messages(session_id))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, assistant: Assistant) -> R[str]:
    return R.ok(await assistant.delete_session(session_id))

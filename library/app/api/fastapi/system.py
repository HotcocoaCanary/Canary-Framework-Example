"""``/api/health`` —— 图里**实际**装的是哪个实现。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.api.fastapi.bridge import use
from app.common.response import R
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from config import AppConfig

router = APIRouter(tags=["系统"])

Config = Annotated[AppConfig, use(AppConfig)]
Db = Annotated[Database, use(Database)]
Embeddings = Annotated[EmbeddingModel, use(EmbeddingModel)]
Chat = Annotated[ChatModel, use(ChatModel)]


def report(config: AppConfig, database: Database, embeddings: EmbeddingModel, chat: ChatModel) -> dict[str, str]:
    """What the graph actually holds —— 两栈的 ``/api/health`` 必须答得一样。"""
    return {
        "status": "ok",
        "storage": config.storage,
        "dialect": database.dialect,
        "embedding_model": type(embeddings).__name__,
        "chat_model": type(chat).__name__,
    }


@router.get("/health")
async def health(config: Config, database: Db, embeddings: Embeddings, chat: Chat) -> R[dict[str, str]]:
    return R.ok(report(config, database, embeddings, chat))

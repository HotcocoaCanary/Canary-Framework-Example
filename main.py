import os

from app.module.chat_module.module import ChatModule
from app.module.db_module.module import DBModule
from app.module.knowledge_module.module import KnowledgeModule
from app.shared.aliyun.module import AliyunModule
from app.shared.llm.client import LLMClient
from app.shared.pigx.module import PigXModule
from app.shared.worker.chunk_worker import ChunkWorker
from app.shared.worker.parse_worker import ParseWorker
from cf import module
from cf.web.fastapi import web, get, WebCanary

log_level = os.getenv("LOG_LEVEL", "INFO").upper()


@web(routers=[])
@module(
    name="AppModule",
    services=[
        DBModule,
        PigXModule,
        AliyunModule,
        KnowledgeModule,
        ChatModule,
        LLMClient,
        ParseWorker,
        ChunkWorker,
    ],
)
class AppModule:
    @get("/health", tags=["系统"], summary="健康检查")
    async def health(self):
        return {"status": "ok"}


if __name__ == "__main__":
    WebCanary(
        AppModule,
        log_level=log_level,
        fastapi_kwargs={
            "title": "Canary-Agent",
            "version": "0.1.0",
            "description": "基于 Canary Framework + LangGraph 的 AI 平台",
            "docs_url": "/docs",
            "redoc_url": "/redoc",
            "openapi_url": "/openapi.json",
        },
    ).start(
        host="0.0.0.0",
        port=8000
    )
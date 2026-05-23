import asyncio

from app.module.chat_module.module import ChatModule
from app.module.db_module.module import DBModule
from app.module.knowledge_module.module import KnowledgeModule
from app.shared.aliyun.module import AliyunModule
from app.shared.llm.client import LLMClient
from app.shared.pigx.module import PigXModule
from app.shared.worker.chunk_worker import ChunkWorker
from app.shared.worker.parse_worker import ParseWorker
from cf import module, config
from cf.web.fastapi import web, get, WebCanary


@config
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    title: str = "Canary-Agent"
    version: str = "0.1.0"
    description: str = "基于 Canary Framework + LangGraph 的 AI 平台"
    docs_url: str = "/docs"
    redoc_url: str = "/redoc"
    openapi_url: str = "/openapi.json"


@web()
@module(
    name="AppModule",
    config=AppConfig,
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


async def main():
    app = WebCanary(AppModule)
    await app.init()
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())

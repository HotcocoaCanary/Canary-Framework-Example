import asyncio

from canary_framework import module
from canary_framework.web.fastapi import get, WebCanary
from config import AppConfig

from app.module.chat_module.module import ChatModule
from app.module.collection_module.module import CollectionModule
from app.module.db_module.module import DBModule
from app.module.file_module.module import FileModule
from app.module.knowledge_module.module import KnowledgeModule
from app.shared.aliyun.module import AliyunModule
from app.shared.embedding.embedding_service import EmbeddingService
from app.shared.llm.client import LLMClient
from app.shared.pigx.module import PigXModule


@module(
    name="AppModule",
    services=[
        DBModule,
        PigXModule,
        AliyunModule,
        KnowledgeModule,
        FileModule,
        CollectionModule,
        ChatModule,
        LLMClient,
        EmbeddingService,
    ],
)
class AppModule:
    @get("/health", tags=["系统"], summary="健康检查")
    async def health(self):
        return {"status": "ok"}


async def main():
    app = WebCanary(AppModule)
    await app.config(config=AppConfig())
    await app.init()
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())

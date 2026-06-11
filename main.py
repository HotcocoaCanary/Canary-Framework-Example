"""Entry point for Canary-Agent application.

Supports running both directly and via Docker (Dockerfile uses 'python main.py').
"""
import asyncio

import uvicorn
from canary_framework import module, after_init
from canary_framework.core import ModuleBase

from app.module.collection.module import CollModule
from app.module.db.module import DBModule
from app.module.file.module import FileModule
from app.module.kb.module import KBModule
from app.shared.aliyun.module import AliyunModule
from config import AppConfig


@module(
    services=[
        AppConfig,
        DBModule,
        AliyunModule,
        KBModule,
        FileModule,
        CollModule,
    ],
)
class AppModule(ModuleBase):
    config: AppConfig

    @after_init
    def _bind_config(self):
        if self._cf_registry is not None:
            self._cf_registry._cf_docs_registered = False


async def main():
    app = AppModule()
    await app.init()
    uvicorn.run(app, host="0.0.0.0", port=8010, lifespan="on")


if __name__ == "__main__":
    asyncio.run(main())

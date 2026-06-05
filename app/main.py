import asyncio

import uvicorn
from canary_framework import module, after_init
from canary_framework.core.module import ModuleBase

from app.config import AppConfig, load_env
from app.module.db.module import DBModule
from app.shared.aliyun.module import AliyunModule
from app.module.kb.service import KbService
from app.module.kb.router import KBRouter
from app.module.file.service import FileService
from app.module.file.router import FileRouter
from app.module.collection.service import CollService
from app.module.collection.router import CollRouter


@module(
    services=[
        AppConfig,
        DBModule,
        AliyunModule,
        KbService,
        FileService,
        CollService,
        KBRouter,
        FileRouter,
        CollRouter,
    ],
)
class AppModule(ModuleBase):
    config: AppConfig

    @after_init
    def _bind_config(self):
        self.config = self.AppConfig
        if self._cf_registry is not None:
            self._cf_registry._cf_docs_registered = False


async def setup():
    load_env()
    app = AppModule()
    await app.init()
    return app


if __name__ == "__main__":
    app = asyncio.run(setup())
    cfg = app.config
    uvicorn.run(app, host=cfg.host, port=cfg.port, lifespan="on")

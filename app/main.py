import asyncio

import uvicorn
from canary_framework import module, after_init
from canary_framework.core.module import ModuleBase

from app.config import AppConfig, load_env
from app.module.collection.module import CollModule
from app.module.db.module import DBModule
from app.module.file.module import FileModule
from app.module.kb.module import KBModule
from app.shared.aliyun.module import AliyunModule


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


async def setup():
    load_env()
    app = AppModule()
    await app.init()
    return app


if __name__ == "__main__":
    uvicorn.run(asyncio.run(setup()), host="localhost", port=8010,lifespan="on")

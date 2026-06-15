"""Entry point for Canary-Agent application.

Supports running both directly and via Docker (Dockerfile uses 'python main.py').
"""

import uvicorn
from canary_framework import module
from canary_framework.core import ModuleBase

from app.module.collection.module import CollModule
from app.module.db.module import DBModule
from app.module.file.module import FileModule
from app.module.kb.module import KBModule
from app.shared.aliyun.module import AliyunModule
from config import AppConfig


@module(
    services=[
        DBModule,
        AliyunModule,
        KBModule,
        FileModule,
        CollModule,
    ],
    config=AppConfig,
)
class AppModule(ModuleBase):
    pass


if __name__ == "__main__":
    app = AppModule()
    app.init()
    uvicorn.run(app, host="0.0.0.0", port=8010, lifespan="on")

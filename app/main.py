import asyncio

import uvicorn
from canary_framework import module

from app.module.collection.router import CollRouter
from app.module.file.router import FileRouter
from app.module.kb.router import KBRouter
from config import AppConfig


@module(
    services=[
        FileRouter,
        KBRouter,
        CollRouter
    ],
)
class AppModule:
    pass


async def setup():
    cfg = AppConfig()
    app = AppModule()
    await app.configure(cfg)
    await app.init()
    return app, cfg


if __name__ == "__main__":
    app, cfg = asyncio.run(setup())
    uvicorn.run(app, host=cfg.host, port=cfg.port, lifespan="on")

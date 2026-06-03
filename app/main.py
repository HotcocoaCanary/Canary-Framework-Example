import asyncio

import uvicorn
from canary_framework import module

from app.module.db.module import DBModule
from config import AppConfig


@module(
    services=[
        DBModule
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

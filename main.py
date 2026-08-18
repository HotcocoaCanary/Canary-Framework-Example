"""Canary-Agent application entry point for Canary Framework 0.9.

Canary 0.9 replaces the old module/service/router registry with a small
dependency graph built from ``@cocoa`` units.  The HTTP extension uses
``@web_cocoa`` and ordinary ``@get``/``@post`` route markers.
"""

import asyncio
from typing import Any

import uvicorn
from canary_framework import Canary
from canary_framework.web import web_cocoa
from canary_framework.web.core.openapi import build_openapi
from canary_framework.web.decorator.introspect import routes_of

from app.module.collection.router import CollRouter
from app.module.collection.service import CollService
from app.module.file.router import FileRouter
from app.module.file.service import FileService
from app.module.kb.router import KBRouter
from app.module.kb.service import KbService


@web_cocoa(
    deps=[CollService, FileService, KbService],
    title="Canary-Agent API",
    version="0.1.0",
)
class AppApi(KBRouter, FileRouter, CollRouter):
    """Single HTTP unit collecting all application routes.

    Canary 0.9 exposes one serving app per cocoa.  Keeping the route mixins
    separate preserves the existing feature boundaries while this class gives
    the web extension one aggregate route holder.
    """


class AppModule(Canary):
    """Compatibility façade retaining the project's historical import name."""

    def __init__(self) -> None:
        super().__init__(AppApi)

    @property
    def asgi_app(self) -> "AppModule":
        return self

    def openapi(self) -> dict[str, Any]:
        """Return the same OpenAPI document served at ``/openapi.json``."""
        api = self[AppApi]
        meta = getattr(type(api), "__canary_web__", {})
        return build_openapi(
            meta.get("title", "Canary API"),
            meta.get("version", "0.1.0"),
            [(method, path, api, fn) for method, path, fn in routes_of(api)],
        )


def create_app() -> AppModule:
    return AppModule()


async def setup() -> AppModule:
    app = create_app()
    await app.init()
    await app.start()
    return app


if __name__ == "__main__":
    application = asyncio.run(setup())
    uvicorn.run(application, host="0.0.0.0", port=8010, lifespan="on")

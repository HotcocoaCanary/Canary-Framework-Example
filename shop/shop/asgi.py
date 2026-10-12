"""The existing FastAPI application —— and the four lines that mount the graph.

已有的 FastAPI 应用。整个迁移的接缝就是 ``lifespan`` 里那几行：

```python
async with ShopGraph() as root:     # 启动整张图
    api = APIRouter(prefix="/v2")
    mount(root, api)                # 把图上的路由单元挂进去
    app.include_router(api)
    bridge.bind(root)               # 老路由取单元的桥
    yield
```

和另外两个场景的分水岭在这里：**进程的主人是 uvicorn，不是 Canary**。所以
``uvicorn shop.asgi:app --reload`` 照常用，``--workers`` 也照常用；代价是一个进程只有
一个应用、一个端口，而且生命周期由 ASGI 的 lifespan 驱动（见
``relay`` 与 ``pipeline`` 的另一种选择）。

``mount()`` 有一条要记住的性质：**它没有反操作**。路由被加到应用上，图停了也不会被摘下
来——``@stop`` 之后那些路由还在，只是背后的单元已经空了。所以同一个应用对象不要进出
lifespan 两次（见 tests/test_framework_boundaries.py 里的两条【毛病】）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from canary_framework.asgi.fastapi import mount
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from shop import bridge, legacy
from shop.catalog import CatalogNotLoaded
from shop.graph import ShopGraph

logger = logging.getLogger("shop")

#: 新模块挂在这个前缀下，和老的 ``/v1`` 并排。
NEW_API_PREFIX = "/v2"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the graph for as long as the application runs.

    应用活着的时候，图就活着。
    """
    async with ShopGraph() as root:
        api = APIRouter(prefix=NEW_API_PREFIX)
        mount(root, api)  # ← 迁移的全部接缝
        app.include_router(api)
        bridge.bind(root)
        logger.info("%s 已就绪：%s 之下是新模块", root.config.store_name, NEW_API_PREFIX)
        try:
            yield
        finally:
            bridge.unbind()


def create_app() -> FastAPI:
    """The application, exactly as it was —— 加一个 lifespan，加一行 include_router。"""
    app = FastAPI(title="青瓷商城后台", version="2.0.0", lifespan=lifespan)
    app.include_router(legacy.router)

    @app.get("/", tags=["老接口"])
    async def index() -> dict[str, str]:
        return {"v1": "老接口", NEW_API_PREFIX: "迁过来的模块", "docs": "/docs"}

    async def not_loaded(_: Request, error: Exception) -> JSONResponse:
        # 图不在运行时打新接口：说清楚原因，而不是 500 一个 AttributeError。
        return JSONResponse({"detail": str(error)}, status_code=503)

    async def bad_request(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    app.add_exception_handler(CatalogNotLoaded, not_loaded)
    app.add_exception_handler(ValueError, bad_request)
    app.add_exception_handler(KeyError, lambda *_: JSONResponse({"detail": "没有这个商品"}, status_code=404))
    return app


#: ``uvicorn shop.asgi:app`` —— 老的启动方式一点没变。
app = create_app()

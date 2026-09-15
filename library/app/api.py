"""The ASGI application — FastAPI owns HTTP, Canary owns the object graph.

0.9.x 里 ``Canary`` 本身就是 ASGI 应用：lifespan 驱动生命周期，``@web_cocoa`` 单元把
路由并进同一个 app。0.10.0 删掉了 ``canary_framework.web``，框架的定位收回到依赖注入
与生命周期本身，于是这两件事分给了两个库：

* **FastAPI** —— 路由、请求校验、状态码、OpenAPI 与 ``/docs``。
* **Canary** —— 单元之间的依赖、构造顺序、启动与回收。

两者的接触面只有 ``app/wiring.py`` 那一个文件，三件事：lifespan 对接、按类型取单元、
领域异常落地。分开之后每一侧都是该领域里最普通的写法——这大概是这次重写最大的收获：
不需要为了用框架而学一套只在这个框架里成立的 web 约定。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, FastAPI

from app.common.response import R
from app.composition import LibraryApi
from app.module.catalog.router import router as catalog_router
from app.module.chat.router import router as assistant_router
from app.module.loan.router import router as circulation_router
from app.module.rag.router import router as rag_router
from app.module.reader.router import router as reader_router
from app.wiring import install_error_handlers, lifespan, unit

system_router = APIRouter(prefix="/api", tags=["系统"])

Root = Annotated[LibraryApi, unit(LibraryApi)]


@system_router.get("/health")
async def health(root: Root) -> R[dict[str, str]]:
    return R.ok(root.health())


def create_app() -> FastAPI:
    """Build the ASGI app. ``lifespan`` 启动整张图，退出时逆序回收。"""
    app = FastAPI(
        title="智能图书馆管理系统 API",
        version="1.0.0",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    for router in (
        system_router,
        catalog_router,
        reader_router,
        circulation_router,
        rag_router,
        assistant_router,
    ):
        app.include_router(router)
    return app


app = create_app()

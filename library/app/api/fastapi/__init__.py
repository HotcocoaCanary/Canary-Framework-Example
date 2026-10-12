"""The native FastAPI stack —— a plain FastAPI application, served by our ``Server``.

这是**两层 HTTP 之一**（另一个是 ``app/api/canary/``，路由与应用都是单元）。业务代码一份
也不多：``app/module/*/service.py``、``app/infra/``、``config.py`` 都是共用的。

这一层里**没有任何框架的 web 概念**：模块级的 ``APIRouter``、普通函数、``Depends``，就是
最普通的 FastAPI 写法。框架只出两样东西：

* ``Services`` —— 一个组合根单元，依赖每个 service，但不认识 HTTP。图由它启动。
* ``Gateway`` —— 服务器单元，在 ``@init`` 里把这个 FastAPI 应用赋给 ``self.app``。
  ``Server`` 服务的是 ASGI 应用，不问出处，所以 FastAPI 对象照样服务。

接口怎么拿到单元：靠 ``bridge.py`` 那座桥（一个 ``Depends`` 读 ``app.state.graph``，再按
类型取单元）。路由单元那一侧不需要它——那边写 ``catalog = dep(CatalogService)``。

**生命周期只有一套。** 图由 Canary 启动（``Gateway`` 或 ``async with Services()``），所以
这个 FastAPI 应用不用 lifespan；``Server`` 也不向它发 lifespan 消息。
"""

from __future__ import annotations

from canary_framework import Canary, dep, init, stop
from canary_framework.web.asgi.server import Server
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.fastapi import catalog, chat, loan, rag, reader, system
from app.api.fastapi.bridge import attach
from app.common.errors import DomainError
from app.common.response import R
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.service import CatalogService
from app.module.chat.service import AssistantService
from app.module.loan.service import CirculationService
from app.module.rag.service import RagService
from app.module.reader.service import ReaderService
from config import AppConfig


class Services(Canary):
    """The composition root —— 依赖每个 service，但不认识 HTTP。

    原生 FastAPI 那一侧没有"应用单元"，所以要有一个单元把业务那张图拢起来，否则没人知道
    该启动谁。路由单元那一侧不需要这个：应用单元本身就是根。
    """

    config = dep(AppConfig)
    database = dep(Database)
    embeddings = dep(EmbeddingModel)
    chat_model = dep(ChatModel)

    catalog = dep(CatalogService)
    readers = dep(ReaderService)
    circulation = dep(CirculationService)
    rag = dep(RagService)
    assistant = dep(AssistantService)


async def on_domain_error(_: Request, error: Exception) -> JSONResponse:
    """Turn domain errors into the envelope — one place, for every route."""
    assert isinstance(error, DomainError)
    return JSONResponse(
        R.fail(error.message, error.code).model_dump(mode="json"), status_code=error.code
    )


def create_app(root: Canary) -> FastAPI:
    """Build the FastAPI application and attach it to a running graph.

    建出 FastAPI 应用，并把启动好的图挂在它身上。``root`` 可以是 ``Services``，也可以是
    图上任何一个单元——``unit()`` 从图上按类型取，不在乎从哪个单元出发。
    """
    app = FastAPI(title="智能图书馆管理系统 API", version="1.0.0")
    api = APIRouter(prefix="/api")
    for module in (system, catalog, reader, loan, rag, chat):
        api.include_router(module.router)
    app.include_router(api)
    app.add_exception_handler(DomainError, on_domain_error)
    attach(app, root)
    return app


class Gateway(Server, access_log=False):
    """The listener for this stack —— ``python main.py --stack fastapi``.

    ``@init`` 里给 ``self.app`` 赋一个 FastAPI 对象：``Server`` 服务任何 ASGI 应用，所以
    "换服务器"这件事不需要应用那边配合。此时 ``Services`` 的 ``@init`` 已经跑过，它的
    ``@start``（建引擎、建表）还没有——但接口要到开始服务之后才会被调到，时序是对的。
    """

    services = dep(Services)

    host = "0.0.0.0"
    port = 8110

    @init
    def build(self) -> None:
        self.app = create_app(self.services)

    @stop
    async def forget(self) -> None:
        # 应用随服务器一起作废：图停了之后它不该还能从 state 上取到单元。
        self.app.state.graph = None  # type: ignore[union-attr]

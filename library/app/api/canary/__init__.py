"""The Canary stack — routers and the application are units.

这是**两层 HTTP 之一**（另一个是 ``app/api/fastapi/``，一个原生 FastAPI 应用）。业务代码
一份也不多：``app/module/*/service.py``、``app/infra/``、``config.py`` 都是共用的。

这一层的三件事：

* **路由是单元**：``dep(CatalogService)`` 写在路由单元上，接口方法是绑定方法，直接用
  ``self.catalog``——没有 ``Depends``，也没有"按类型从图里取单元"的那层桥（对照
  ``app/api/fastapi/bridge.py``）；
* **应用也是单元**，而且**它自己就是一个 ASGI 应用**：``await api(scope, receive, send)``。
  所以它既能交给本框架的 ``Server``（``main.py``），也能直接交给 uvicorn（``asgi.py``）；
* 领域异常用 ``@error(DomainError)`` 标记应用单元的方法，返回 ``Response.json(...)``。

``/openapi.json`` 是这一层自己写的：框架只公开接口表（``App.endpoints``），照着它生成文档的
那个函数在 ``openapi.py``。

没有的东西：``/docs`` 这类页面、WebSocket、表单上传。换来的是只依赖 pydantic。
"""

from __future__ import annotations

from typing import Any

from canary_framework import dep, init
from canary_framework.web.asgi.app import App, Request, Response, Router, error, get
from canary_framework.web.asgi.server import Server

from app.api.canary.catalog import CatalogApi
from app.api.canary.chat import AssistantApi
from app.api.canary.loan import CirculationApi
from app.api.canary.openapi import openapi
from app.api.canary.rag import RagApi
from app.api.canary.reader import ReaderApi
from app.common.errors import DomainError
from app.common.response import R
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from config import AppConfig


class SystemApi(Router):
    """``/api/health`` —— 图里**实际**装的是哪个实现。"""

    config = dep(AppConfig)
    database = dep(Database)
    embeddings = dep(EmbeddingModel)
    chat_model = dep(ChatModel)

    @get("/health")
    async def health(self) -> R[dict[str, str]]:
        return R.ok(self.report())

    def report(self) -> dict[str, str]:
        return {
            "status": "ok",
            "storage": self.config.storage,
            "dialect": self.database.dialect,
            "embedding_model": type(self.embeddings).__name__,
            "chat_model": type(self.chat_model).__name__,
        }


class Api(Router, prefix="/api"):
    """Everything under ``/api`` —— 依赖一个路由单元，就是把它挂在自己之下。"""

    system = dep(SystemApi)
    catalog = dep(CatalogApi)
    readers = dep(ReaderApi)
    circulation = dep(CirculationApi)
    rag = dep(RagApi)
    assistant = dep(AssistantApi)


class LibraryApi(App):
    """The web application. 它自己不监听——见下面的 ``Gateway``。"""

    api = dep(Api)

    @error(DomainError)
    async def on_domain_error(self, _: Request, exc: DomainError) -> Response:
        """Turn domain errors into the envelope — one place, for every route."""
        return Response.json(R.fail(exc.message, exc.code), status=exc.code)

    @init
    def describe(self) -> None:
        """Write the OpenAPI document once — 接口表在基类的 ``@init`` 里已经建好。

        文档只描述业务接口，不描述它自己，与 FastAPI 那一层的做法一致。
        """
        described = [e for e in self.endpoints if e.path != "/openapi.json"]
        self.document = openapi(described, "智能图书馆管理系统 API", "1.0.0")

    @get("/openapi.json")
    async def spec(self) -> dict[str, Any]:
        return self.document


class Gateway(Server, access_log=False):
    """The listener for this stack —— ``python main.py --stack canary``.

    服务器单元服务的是 ASGI 应用，不问出处；这里给它的是本栈的应用单元。默认端口与
    FastAPI 版不同，于是两个栈可以同时起着，用同一个脚本压。
    """

    library = dep(LibraryApi)

    host = "0.0.0.0"
    port = 8010

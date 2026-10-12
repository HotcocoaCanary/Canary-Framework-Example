"""The FastAPI stack — one of the two HTTP layers over the same business code.

这是**两层 HTTP 之一**（另一个是 ``app/api/web/``，用自研的 ``canary_framework.asgi.web``）。
两边的业务代码一份也不多：``app/module/*/service.py``、``app/infra/``、``config.py`` 都是
共用的，这里只有路由与应答格式。两边对外的路径、状态码、响应体一致，所以
``tests/`` 里同一套行为测试对两个栈各跑一遍（见 ``tests/conftest.py``）。

本栈独有的东西：OpenAPI 与 ``/docs``、``tags``、FastAPI 的校验错误格式、
``Depends`` 生态。

路由树就是依赖图：``Api`` 依赖五个模块的路由单元，于是它们挂在 ``/api`` 之下，前缀逐层
叠加；``LibraryApi`` 依赖 ``Api``，于是整棵树挂在这个 FastAPI 应用上。没有单独的注册步骤，
也没有"按类型从图里取单元"的那层胶水——接口方法是绑定方法，直接用 ``self`` 上的依赖。

上一版这里是 FastAPI 的 ``APIRouter`` + lifespan + ``Depends(provide(Cls))``，接缝集中在
``app/wiring.py``。换成 ``canary_framework.asgi.fastapi`` 之后那个文件不需要了：

* 生命周期对接 —— 没有了。应用自己是图上的单元，监听它的 ``Gateway`` 也是（见 ``main.py``）。
* 取用单元 —— 没有了。``catalog = dep(CatalogService)`` 写在路由单元上。
* 领域异常落地 —— 还在，下面 ``LibraryApi`` 的 ``@init`` 里，一处。

参数解析、校验、状态码、OpenAPI 与 ``/docs`` 仍然全是 FastAPI 的。
"""

from __future__ import annotations

from canary_framework import asgi, dep, init
from canary_framework.asgi.fastapi import App, Router, get
from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.fastapi.catalog import CatalogApi
from app.api.fastapi.chat import AssistantApi
from app.api.fastapi.loan import CirculationApi
from app.api.fastapi.rag import RagApi
from app.api.fastapi.reader import ReaderApi
from app.common.errors import DomainError
from app.common.response import R
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from config import AppConfig


class SystemApi(Router, tags=["系统"]):
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


class LibraryApi(App, title="智能图书馆管理系统 API", version="1.0.0"):
    """The FastAPI application. 它自己不监听——见下面的 ``Gateway``。"""

    api = dep(Api)

    @init
    def install_error_handlers(self) -> None:
        """Turn domain errors into the envelope — one place, for every route.

        成功路径由各接口的返回注解 ``R[T]`` 描述；失败路径走这里，状态码取
        ``DomainError.code``，信封里的 ``code`` 与状态行保持一致。服务层只 ``raise``，
        不认识 HTTP。
        """
        self.app.add_exception_handler(DomainError, self.on_domain_error)

    async def on_domain_error(self, _: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, DomainError)
        return JSONResponse(
            R.fail(error.message, error.code).model_dump(mode="json"),
            status_code=error.code,
        )


class Gateway(asgi.Server, access_log=False):
    """The listener for this stack —— ``python main.py --stack fastapi``.

    两个栈各有一个 ``Server``：``dep()`` 是类上的声明，所以"听哪个应用"这件事只能由类
    决定，不能在运行期挑。两个端口默认不同，于是两个栈可以同时起着对比。

    类参数原样传给 ``uvicorn.Config``——压测时访问日志会严重干扰结果，所以这里关掉。
    """

    library = dep(LibraryApi)

    host = "0.0.0.0"
    port = 8010

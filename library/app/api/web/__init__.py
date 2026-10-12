"""The web stack — the same HTTP surface, on ``canary_framework.asgi.web``.

这是**两层 HTTP 之一**（另一个是 ``app/api/fastapi/``）。业务代码一份也不多：
``app/module/*/service.py``、``app/infra/``、``config.py`` 都是共用的。

和 FastAPI 版逐行对照，差别只有四处：

* 导入 ``canary_framework.asgi.web`` 而不是 ``...asgi.fastapi``；
* 路由单元没有 ``tags``——这个包不生成 OpenAPI，标签无处可去；
* 成功状态码写 ``@post(status=201)``（FastAPI 是 ``status_code=``）；本项目一律用信封，
  所以两边都没用到；
* 领域异常用 ``@error(DomainError)`` 标记应用单元的方法，返回 ``Response.json(...)``；
  FastAPI 版是 ``app.add_exception_handler(...)`` 返回 ``JSONResponse``。

没有的东西：OpenAPI、``/docs``、WebSocket、表单上传。换来的是只依赖 pydantic。
"""

from __future__ import annotations

from canary_framework import asgi, dep
from canary_framework.asgi.web import App, Request, Response, Router, error, get

from app.api.web.catalog import CatalogApi
from app.api.web.chat import AssistantApi
from app.api.web.loan import CirculationApi
from app.api.web.rag import RagApi
from app.api.web.reader import ReaderApi
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


class Gateway(asgi.Server, access_log=False):
    """The listener for this stack —— ``python main.py --stack web``.

    默认端口与 FastAPI 版不同，于是两个栈可以同时起着，用同一个脚本压。
    """

    library = dep(LibraryApi)

    host = "0.0.0.0"
    port = 8011

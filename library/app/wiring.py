"""The seam between Canary's graph and FastAPI's request handling.

0.10.0 把 ``canary_framework.web`` 删掉了，框架只剩依赖注入与生命周期。所以"接 web"
这件事回到应用手里，而它需要的东西恰好只有三样，全在这个文件里：

1. **生命周期对接** —— ``lifespan``。官方迁移表就一句话：
   ``app = FastAPI(lifespan=canary.lifespan)`` 改成自写三行 ``asynccontextmanager``。
   这里是那三行：``async with LibraryApi() as root``，进入时整张图按依赖顺序就位，
   退出时逆序回收，异常照常往上抛。

2. **取用单元** —— ``provide(Cls)``。FastAPI 的依赖系统按类型给 handler 注入东西，
   Canary 的作用域按类型持有实例，两边接起来就是一个查表。注意作用域的粒度是
   **一次运行**，不是一次请求：每个类型一个实例，这正是连接池该有的粒度。请求级的
   工作单元由 service 自己开（``async with self.database.begin()``）。

3. **领域异常落地** —— ``install_error_handlers``。服务层只 ``raise``，不认识 HTTP；
   一处 handler 把 ``DomainError`` 翻成 ``{code, data, msg}`` 信封和对应状态码。

第 3 点相对 0.9.x 是实打实的改善：那时框架删掉了 ``@on_request_error``，异常只能在
每个 handler 里靠 ``await ok(...)`` 接住——漏写一个，领域异常就变成 500，而且只能靠
代码评审发现。换到 FastAPI 之后这条约束由框架保证，全应用一处，不可能漏。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from canary_framework import Canary, scope_of
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.errors import DomainError
from app.common.response import R
from app.composition import LibraryApi


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the graph for the lifetime of the ASGI app.

    ``async with LibraryApi()`` 依次跑 ``init`` 与 ``start``；任一环节失败会先回收已经
    启动的单元，再把最初的异常原样抛出——uvicorn 于是启动失败退出，而不是带着半张图
    开始服务。
    """
    async with LibraryApi() as root:
        app.state.root = root
        yield


def root_of(request: Request) -> LibraryApi:
    """The composition root this request belongs to."""
    return request.app.state.root  # type: ignore[no-any-return]


def provide[T: Canary](cls: type[T]) -> Callable[[Request], T]:
    """A FastAPI dependency that hands back *cls* from the running graph.

    ``scope_of(root).instances`` 就是"类型 → 本次运行的唯一实例"那张表，
    ``dep(...)`` 在内部读的也是它。
    """

    def resolve(request: Request) -> T:
        return scope_of(root_of(request)).instances[cls]  # type: ignore[return-value]

    return resolve


def unit[T: Canary](cls: type[T]):  # noqa: ANN201 —— 返回的是 Annotated 元数据，交给 FastAPI
    """``Annotated`` 形式的 :func:`provide`，用来给 handler 写类型注解。"""
    return Depends(provide(cls))


def install_error_handlers(app: FastAPI) -> None:
    """Turn domain errors into the envelope — one place, for every route.

    成功路径由各 handler 的返回注解 ``R[T]`` 描述；失败路径走这里，状态码取
    ``DomainError.code``，信封里的 ``code`` 与状态行保持一致。
    """

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            R.fail(error.message, error.code).model_dump(mode="json"),
            status_code=error.code,
        )

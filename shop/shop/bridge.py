"""How the legacy routes reach a unit.

老路由怎么拿到图上的单元。

``mount()`` 那一套没有了——框架不再包装 FastAPI，所以"把路由单元挂到你的应用上"这件事也
不存在了。迁移靠的是**协议层的兼容**：我们的服务器服务任何 ASGI 应用，我们的应用单元也能
被任何 ASGI 服务器服务。于是老应用一行不改就能换服务器，新模块作为另一个 ASGI 应用并排
站着（见 ``shop/server.py``）。

剩下的问题只有一个：老路由（普通 FastAPI 函数 + ``Depends``）要用迁过来的业务单元。这就是
这座桥——``app.state.graph`` 加一个 ``Depends``，三行::

    Catalogue = Annotated[Catalog, use(Catalog)]

    @router.get("/v1/stock/{sku}")
    async def stock(sku: str, catalogue: Catalogue) -> dict:
        return catalogue.require(sku).view()

``library`` 与 ``relay`` 两个场景里也各有一座同样形状的桥——三个场景写了三遍，这件事记在
README 里。
"""

from __future__ import annotations

from typing import Annotated, Any

from canary_framework import Canary
from canary_framework.test import unit as lookup
from fastapi import Depends, FastAPI, Request


def attach(app: FastAPI, root: Canary) -> None:
    """Remember the running graph on this application."""
    app.state.graph = root


async def graph(request: Request) -> Canary:
    """The graph this application was attached to."""
    root = getattr(request.app.state, "graph", None)
    if root is None:
        raise RuntimeError("这个 FastAPI 应用还没有挂上图")
    return root


Graph = Annotated[Canary, Depends(graph)]


def use[T: Canary](cls: type[T]) -> Any:
    """A FastAPI dependency that resolves *cls* from the running graph."""

    # async def：同步的依赖函数会被 FastAPI 放进线程池，每个请求多两次线程切换。
    async def resolve(root: Graph) -> T:
        return lookup(root, cls)

    return Depends(resolve)

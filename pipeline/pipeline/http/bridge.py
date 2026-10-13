"""How a native FastAPI endpoint reaches a unit on the graph.

原生 FastAPI 这一侧需要一座桥：接口是模块级的函数，不是单元的方法，所以"要用哪个单元"
没法写成 ``dep(...)``，只能在请求时去图上取。

和 ``library`` / ``relay`` 两个场景里那两座是同一个形状（``app.state.graph`` + 一个
``Depends``）——写第三遍的时候就会想：这东西应该由框架给，还是就该每个项目自己写三行？
目前是后者，而它确实只有三行。

对照 ``pipeline/http/canary.py``：那一侧的路由是单元，``gate = dep(Gate)`` 写在类上。

这座桥的写法在框架文档里有一节：``docs/zh/extensions/server.md`` 的"在别的框架的接口里用
单元"。两处容易写错的地方都在那里写明了：依赖函数必须是 ``async def``（同步的会被 FastAPI
扔进线程池，每请求多两次线程切换，实测吞吐掉到三分之一），以及按类型取单元就用
``canary_framework.test.unit``——生产代码里用它没问题。
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

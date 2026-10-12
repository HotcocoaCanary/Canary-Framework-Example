"""How a native FastAPI endpoint reaches a unit on the graph.

原生 FastAPI 这一侧需要一座桥：接口是模块级的函数，不是单元的方法，所以"要用哪个
service"没法写成 ``dep(...)``，只能在请求时去图上取。

桥只有两件事：

* ``attach(app, root)`` 把启动好的图放在 ``app.state.graph`` 上（``create_app`` 调它）；
* ``use(Cls)`` 是一个 FastAPI 依赖，从那张图上按类型取单元。

放在 ``app.state`` 上而不是模块级全局，是为了一个进程里可以有多张图（测试里就是这样）。

对照 ``app/api/canary/``：那一侧的路由是单元，``catalog = dep(CatalogService)`` 写在类上，
接口方法直接用 ``self.catalog``——这座桥整个不需要。这就是两种写法最实在的差别。

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
    """Remember the running graph on this application.

    把启动好的图记在这个应用上。
    """
    app.state.graph = root


async def graph(request: Request) -> Canary:
    """The graph this application was attached to.

    这个应用挂着的那张图。
    """
    root = getattr(request.app.state, "graph", None)
    if root is None:
        raise RuntimeError("这个 FastAPI 应用还没有挂上图：create_app() 没有被调用过？")
    return root


Graph = Annotated[Canary, Depends(graph)]


def use[T: Canary](cls: type[T]) -> Any:
    """A FastAPI dependency that resolves *cls* from the running graph.

    ``canary_framework.test.unit`` 在这里不是"测试辅助"——它就是"按类型取回单元"，这座桥
    正需要这一个动作。日常代码仍然应当声明依赖（``dep(...)``）。
    """

    # async def：同步的依赖函数会被 FastAPI 放进线程池，每个请求多两次线程切换。
    async def resolve(root: Graph) -> T:
        return lookup(root, cls)

    return Depends(resolve)

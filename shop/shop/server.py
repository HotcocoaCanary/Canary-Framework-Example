"""The two stages of the migration —— both of them just ASGI, on both sides.

迁移分两步，而两步都只是"把 ASGI 的两侧组合起来"：

**阶段一：只换服务器。** 老应用一行不改，由我们的 ``Server`` 服务它。这一步什么都没搬，
但已经拿到了想要的东西——进程的生命周期归 Canary：数据库、缓存、后台任务都是图上的单元，
按依赖顺序启动与回收，而不是靠 FastAPI 的 lifespan 事件手工拼。

**老应用把初始化写在自己的 lifespan 里时，加一个类参数：** ``class Stage1(Server,
lifespan="on")``。默认不发 lifespan 消息（生命周期归 Canary，不该有两套），所以老应用的
``lifespan`` / ``on_event("startup")`` 一次都不会跑——接口照样能通，直到第一个用到那个连接
池的请求打进来。打开之后，应用的启动发生在本单元的 ``@start`` 里、监听之前，回收发生在
``@stop`` 里，启动失败就是 ``Server`` 启动失败（已启动的依赖照常回收）。本项目的
``create_legacy`` 没有 lifespan，所以这里没打开；三条测试把两种情形都钉在
``tests/test_framework_boundaries.py`` 里。

    class Stage1(Server):
        graph = dep(ShopGraph)

        @init
        def build(self) -> None:
            self.app = create_legacy(self.graph)

**阶段二：新模块作为另一个 ASGI 应用并存。** 迁过来的模块是一个应用单元
（``V2Api``，``path = "/v2"``），和老应用一起按路径分发。两者共用同一张图上的业务单元，
所以 ``/v2`` 改掉的库存，``/v1`` 立刻看得见。

    class Stage2(Server):
        graph = dep(ShopGraph)
        v2 = dep(V2Api)

        @init
        def build(self) -> None:
            self.app = dispatch({self.v2.path: self.v2, "/": create_legacy(self.graph)})

**为什么不用"把路由挂到老应用上"。** 那需要框架去包装 FastAPI 的 ``APIRouter``——一个只为
某个框架存在的适配层。按路径分发不需要：两边各是一个 ASGI 应用，``dispatch`` 把它们拼在
一个端口上。老那边继续用它的 ``Depends``，新那边用 ``dep()``，谁也不必迁就谁。

代价是两者的 OpenAPI 是分开的（``/docs`` 只有老应用那一份，新模块那层不生成 OpenAPI），
以及路径前缀要自己对齐（``dispatch`` 不改写 ``path``，所以 ``V2Api`` 下面的路由单元自己
带着 ``/v2``）。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.web.asgi import dispatch
from canary_framework.web.asgi.server import Server

from shop.graph import ShopGraph, V2Api
from shop.legacy import create_legacy


class Stage1(Server, access_log=False):
    """Stage one: the existing application, served by our server unit.

    阶段一：老应用，一行没改。
    """

    graph = dep(ShopGraph)

    host = "0.0.0.0"
    port = 8040

    @init
    def build(self) -> None:
        self.app = create_legacy(self.graph)


class Stage2(Server, access_log=False):
    """Stage two: the migrated modules beside the old application, dispatched by path.

    阶段二：新模块与老应用并存。
    """

    graph = dep(ShopGraph)
    v2 = dep(V2Api)

    host = "0.0.0.0"
    port = 8041

    @init
    def build(self) -> None:
        self.app = dispatch({self.v2.path: self.v2, "/": create_legacy(self.graph)})


#: 阶段名 -> 服务器单元。``dep()`` 是写在类上的声明，所以阶段只能由类决定。
STAGES: dict[str, type[Server]] = {"1": Stage1, "2": Stage2}

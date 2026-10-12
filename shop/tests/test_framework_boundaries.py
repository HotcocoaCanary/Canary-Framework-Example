"""框架边界：协议两侧怎么组合，以及迁移时会咬人的那几条。

上一轮这个文件钉的是 ``mount()`` 的行为。现在框架不再包装 FastAPI，``mount()`` 也没有了
——迁移靠的是**协议层的兼容**：我们的服务器服务任何 ASGI 应用，我们的应用单元也能被任何
ASGI 服务器服务。所以这个文件钉的是那些组合的实际行为。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from canary_framework import Canary, LifecycleError, dep, init, scope_of, start
from canary_framework.test import running, unit
from canary_framework.web.asgi import dispatch
from canary_framework.web.asgi.server import Server
from fastapi import FastAPI

from shop.catalog import Catalog
from shop.graph import ShopGraph, V2Api
from shop.legacy import create_legacy


def connect(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- 应用单元自己就是 ASGI 应用 ---------------------------------------------


async def test_an_application_unit_is_an_asgi_application(v2_client) -> None:
    """``httpx.ASGITransport(app=api)`` —— 打的就是那个单元，没有服务器，也没有端口。"""
    assert (await v2_client.get("/v2/inventory")).status_code == 200


async def test_serving_before_the_lifecycle_says_what_to_do() -> None:
    """没启动就收到请求：说清楚该怎么启动，而不是 ``AttributeError``。"""
    api = V2Api()
    transport = httpx.ASGITransport(app=api, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(LifecycleError, match="before its lifecycle began"):
            await client.get("/v2/inventory")


async def test_an_asgi_server_can_drive_the_graph_through_lifespan() -> None:
    """第二种组合：我们的应用单元 + 原生 ASGI 服务器（``uvicorn module:app``）。

    图由服务器的 lifespan 消息启动与回收——``V2Api()`` 一个实例就是一个完整的 ASGI 应用。
    """
    api = V2Api()
    inbox: asyncio.Queue[dict] = asyncio.Queue()
    sent: list[dict] = []

    async def receive() -> dict:
        return await inbox.get()

    async def send(message: dict) -> None:
        sent.append(message)

    serving = asyncio.create_task(api({"type": "lifespan"}, receive, send))
    await inbox.put({"type": "lifespan.startup"})
    for _ in range(200):
        if sent:
            break
        await asyncio.sleep(0.005)
    assert sent == [{"type": "lifespan.startup.complete"}]
    assert unit(api, Catalog).loaded is True

    async with connect(api) as client:
        assert (await client.get("/v2/inventory")).status_code == 200

    await inbox.put({"type": "lifespan.shutdown"})
    await asyncio.wait_for(serving, timeout=10)
    assert sent[-1] == {"type": "lifespan.shutdown.complete"}
    assert not scope_of(api).entered(start), "停止消息把整张图回收了"


# --- 服务器这一侧 -----------------------------------------------------------


async def test_the_server_serves_whatever_is_callable_and_depended_on() -> None:
    """依赖即服务：直接依赖的可调用单元都在这个端口上，路径取它们的 ``path``。"""

    class Pong(Canary):
        path = "/pong"

        async def __call__(self, scope, receive, send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"pong"})

    class Serving(Server):
        pong = dep(Pong)
        graph = dep(ShopGraph)  # 普通依赖：不可调用，不会被当成应用
        host = "127.0.0.1"
        port = 0

    async with running(Serving) as server:
        url = f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            assert (await client.get("/pong")).text == "pong"
            assert (await client.get("/elsewhere")).status_code == 404


async def test_a_server_with_nothing_to_serve_is_refused() -> None:
    """依赖里没有一个可调用的，也没赋 ``self.app`` —— 这是声明上的错。"""

    class Empty(Server):
        graph = dep(ShopGraph)
        host = "127.0.0.1"
        port = 0

    with pytest.raises(LifecycleError, match="nothing to serve"):
        async with running(Empty):
            pass


async def test_assigning_self_app_takes_over_from_the_dependencies() -> None:
    """赋了 ``self.app`` 就以它为准：依赖的应用单元**不再自动加入**。

    阶段二因此要自己 ``dispatch``——老应用是个 FastAPI 对象，不是单元，只能这么拼。
    """

    class Manual(Server):
        v2 = dep(V2Api)  # 依赖了，但下面没把它写进表里
        graph = dep(ShopGraph)
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = create_legacy(self.graph)

    async with running(Manual) as server:
        url = f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            assert (await client.get("/v1/health")).status_code == 200
            assert (await client.get("/v2/inventory")).status_code == 404  # 依赖了却没被服务


# --- 【迁移时会咬人】老应用自己的 lifespan 不会被调用 ------------------------


async def test_the_server_never_sends_lifespan_to_the_application() -> None:
    """**【迁移要注意】** 我们的 ``Server`` 不向应用发 lifespan 消息，所以老应用自己的
    ``lifespan`` / ``on_event("startup")`` **一次都不会跑**。

    "先只换服务器"这一步因此有个陷阱：老应用如果在 lifespan 里建连接池、热缓存、起后台
    任务，换成由 ``Server`` 服务之后这些**悄悄地不发生了**，而接口照样能通——直到第一个
    用到那个连接池的请求打进来。

    这是设计上的选择（生命周期归 Canary，不该有两套），但迁移时必须把老 lifespan 里的事
    搬成图上的单元。本项目的 ``create_legacy`` 没有 lifespan，就是为了不踩它。
    """
    ran: list[str] = []

    def make() -> FastAPI:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            ran.append("startup")
            yield
            ran.append("shutdown")

        app = FastAPI(lifespan=lifespan)

        @app.get("/ping")
        async def ping() -> dict:
            return {"ok": True}

        return app

    class Legacy(Server):
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = make()

    async with running(Legacy) as server:
        url = f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            assert (await client.get("/ping")).json() == {"ok": True}
    assert ran == [], "老应用的 lifespan 一次都没跑"


# --- dispatch：两个应用在一个端口上 -----------------------------------------


async def test_dispatch_puts_two_applications_on_one_port(graph) -> None:
    """阶段二的拼法：新模块一个应用，老应用另一个，按最长前缀分发。"""
    async with running(V2Api) as v2:
        table = dispatch({v2.path: v2, "/": create_legacy(graph)})
        async with connect(table) as client:
            assert (await client.get("/v2/inventory")).status_code == 200
            assert (await client.get("/v1/health")).status_code == 200
            assert (await client.get("/")).status_code == 200


async def test_dispatch_does_not_rewrite_the_path(graph) -> None:
    """``dispatch`` 只转发不改写，所以 ``/v2`` 下面的路由自己带着这个前缀。

    这是"挂载"与"分发"的区别：挂载会改写 ``path`` / ``root_path``，分发不会。代价是前缀
    要在两处对齐（``V2Api.path`` 与路由单元的 ``prefix``），好处是子应用看到的路径就是
    客户端请求的那个。
    """
    from shop.inventory import InventoryApi

    assert InventoryApi.__canary_web_prefix__ == "/v2/inventory"
    async with running(V2Api) as v2:
        assert v2.path == "/v2"
        table = dispatch({"/v2": v2, "/": create_legacy(graph)})
        async with connect(table) as client:
            # 应用看到的仍是 /v2/inventory，所以它答得出来
            assert (await client.get("/v2/inventory")).status_code == 200
            # 前缀按整段匹配：/v2x 不属于 /v2，落到老应用上
            assert (await client.get("/v2x")).status_code == 404

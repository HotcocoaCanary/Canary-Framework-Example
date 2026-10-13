"""框架边界：协议两侧怎么组合，以及迁移时会咬人的那几条。

上一轮这个文件钉的是 ``mount()`` 的行为。现在框架不再包装 FastAPI，``mount()`` 也没有了
——迁移靠的是**协议层的兼容**：我们的服务器服务任何 ASGI 应用，我们的应用单元也能被任何
ASGI 服务器服务。所以这个文件钉的是那些组合的实际行为。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from canary_framework import Canary, LifecycleError, dep, init, scope_of, start, stop
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


# --- 老应用自己的 lifespan：默认不跑，一个类参数打开 ----------------------


def legacy_with_lifespan(ran: list[str]):
    """A FastAPI application that does its setup in its own lifespan.

    别的框架的应用常常这样：连接池、热缓存、后台任务都写在 lifespan 里。
    """
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


async def test_by_default_the_server_does_not_send_lifespan() -> None:
    """**默认不发**：生命周期归 Canary，不该有两套。

    上一轮这条是作为"迁移会咬人"的一条记在这里的——"先只换服务器"时，老应用如果把初始化
    写在 lifespan 里，换完之后那些事**悄悄地不发生了**，而接口照样能通，直到第一个用到
    连接池的请求打进来。现在有了显式开关（见下一条），默认值仍然是不发。
    """
    ran: list[str] = []

    class Quiet(Server):
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = legacy_with_lifespan(ran)

    async with running(Quiet) as server:
        url = f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            assert (await client.get("/ping")).json() == {"ok": True}
    assert ran == [], "默认不向应用发 lifespan 消息"


async def test_lifespan_on_runs_the_application_s_own_lifespan() -> None:
    """``class Gateway(Server, lifespan="on")`` —— 老应用的 lifespan 照常跑。

    顺序是对的：应用的启动发生在 ``Server`` 的 ``@start`` 里、**监听之前**，回收发生在
    ``@stop`` 里。所以"先只换服务器"这一步不必先把老 lifespan 搬成单元——想搬再搬。
    """
    ran: list[str] = []

    class Loud(Server, lifespan="on"):
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = legacy_with_lifespan(ran)

    async with running(Loud) as server:
        assert ran == ["startup"], "监听之前就启动了"
        url = f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            assert (await client.get("/ping")).json() == {"ok": True}
    assert ran == ["startup", "shutdown"], "@stop 里回收"


async def test_a_failing_application_lifespan_fails_the_server() -> None:
    """应用的 lifespan 启动失败 = ``Server`` 启动失败，已启动的依赖照常回收。

    这一条值得钉：uvicorn 自己遇到 lifespan 失败是 ``sys.exit``，那会绕过回收。
    """
    reclaimed: list[str] = []

    class Resource(Canary):
        @init
        def note(self) -> None:
            reclaimed.append("init")

        @stop
        async def release(self) -> None:
            # 注意是 @stop 钩子，不是覆盖 stop() 方法：回收跑的是钩子，
            # stop() 只在根单元上被调用一次。
            reclaimed.append("stop")

    def broken() -> FastAPI:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            raise RuntimeError("老应用的缓存预热失败")
            yield

        return FastAPI(lifespan=lifespan)

    class Doomed(Server, lifespan="on"):
        resource = dep(Resource)
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = broken()

    with pytest.raises(RuntimeError, match="lifespan failed during startup"):
        async with running(Doomed):
            pass
    assert reclaimed == ["init", "stop"]


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

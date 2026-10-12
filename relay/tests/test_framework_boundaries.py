"""框架边界：这个场景逼出来的框架行为，一条一条钉住。

和 ``library`` / ``telemetry`` 的同名文件一样，这些测试不测业务，只记录**框架当前的
行为**：既是回归保护，也是一份可执行的说明。每条都注明它对应框架的哪个决定。

标了 **【毛病】** 的几条是本场景试出来的问题，断言写的是"现在是什么样"，注释写的是
"应该是什么样"——框架改了的话，这些测试会红，那正是想要的。
"""

from __future__ import annotations

import asyncio
import socket
import time

import pytest
from canary_framework import Canary, LifecycleError, asgi, dep, init, scope_of, stop
from canary_framework.test import running, unit

from relay import server
from relay.clock import Clock
from relay.fleet import Fleet
from relay.http import root as root_class
from relay.metrics import Metrics
from relay.secrets import SecretStore
from relay.settings import AdminSettings, EdgeSettings

# -- 辅助：几个最小的应用单元 ---------------------------------------------


async def answer(scope, receive, send) -> None:
    """An ASGI application that reports which path it saw."""
    if scope["type"] != "http":
        return
    body = scope["path"].encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class Echo(asgi.App):
    path = "/echo"

    @init
    def build(self) -> None:
        self.app = answer


class AlsoEcho(asgi.App):
    """Another application unit on the **same** path."""

    path = "/echo"

    @init
    def build(self) -> None:
        self.app = answer


# -- Server：依赖即服务，以及它的两种失败 ----------------------------------


async def test_two_applications_on_one_path_is_refused() -> None:
    """``asgi`` 文档的承诺：两个应用的 ``path`` 相同时 ``start()`` 抛 ``LifecycleError``。"""

    class Clash(asgi.Server):
        one = dep(Echo)
        two = dep(AlsoEcho)
        host = "127.0.0.1"
        port = 0

    with pytest.raises(LifecycleError, match="two apps answer"):
        async with running(Clash):
            pass


async def test_a_server_with_nothing_to_serve_is_refused() -> None:
    """依赖里没有应用单元、也没有赋 ``self.app`` —— 这是声明上的错，不是运行时的 404。"""

    class Empty(asgi.Server):
        clock = dep(Clock)  # 依赖了东西，但没有一个是 App
        host = "127.0.0.1"
        port = 0

    with pytest.raises(LifecycleError, match="nothing to serve"):
        async with running(Empty):
            pass


async def test_assigning_self_app_takes_over_from_the_dependencies() -> None:
    """赋了 ``self.app`` 就以它为准：依赖的应用单元**不再自动加入**，漏写不会报错。

    ``AdminServer`` 用的就是这条；代价也在这里——它必须自己把 ``Metrics`` 写进
    ``dispatch`` 的表里。
    """

    class Manual(asgi.Server):
        echo = dep(Echo)  # 依赖了，但下面没把它写进表里
        host = "127.0.0.1"
        port = 0

        @init
        def build(self) -> None:
            self.app = asgi.dispatch({"/only": answer})

    import httpx

    async with (
        running(Manual) as server,
        httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}") as client,
    ):
        assert (await client.get("/only")).status_code == 200
        assert (await client.get("/echo")).status_code == 404  # 依赖了却没被服务


async def test_a_busy_port_fails_the_start_and_reclaims_what_started() -> None:
    """端口被占用时 ``start()`` 抛 ``OSError``，已启动的依赖照常回收。"""
    reclaimed: list[str] = []

    class Noted(asgi.App):
        path = "/"

        @init
        def build(self) -> None:
            self.app = answer

        @stop
        async def note(self) -> None:
            reclaimed.append("app")

    squatter = socket.create_server(("127.0.0.1", 0))
    try:
        taken = squatter.getsockname()[1]

        class Blocked(asgi.Server):
            app_unit = dep(Noted)
            host = "127.0.0.1"
            port = taken

        with pytest.raises(OSError):
            async with running(Blocked):
                pass
    finally:
        squatter.close()
    assert reclaimed == ["app"]  # 应用单元已经启动过，所以它被回收了


# -- 回收顺序：依赖顺序就是停机顺序 ----------------------------------------


async def test_stop_runs_dependents_before_dependencies() -> None:
    """进入依赖在前，离开本单元在前——所以"先停止监听，再回收应用和状态"是免费的。"""
    order: list[str] = []

    class Leaf(Canary):
        @stop
        async def note(self) -> None:
            order.append("leaf")

    class Served(asgi.App):
        leaf = dep(Leaf)
        path = "/"

        @init
        def build(self) -> None:
            self.app = answer

        @stop
        async def note(self) -> None:
            order.append("app")

    class Listening(asgi.Server):
        served = dep(Served)
        host = "127.0.0.1"
        port = 0

        @stop
        async def note(self) -> None:
            # 基类的 @stop（关闭监听）按 MRO 先跑，所以这一条发生在套接字关掉之后
            order.append("server")

    class Root(Canary):
        listening = dep(Listening)

        @stop
        async def note(self) -> None:
            order.append("root")

    async with running(Root):
        pass
    assert order == ["root", "server", "app", "leaf"]


async def test_an_application_shared_by_two_servers_stops_once_and_last() -> None:
    """同一个应用单元被两个 ``Server`` 依赖：一个实例，一次回收，且在两个端口都关掉之后。"""
    order: list[str] = []

    class Shared(asgi.App):
        path = "/"

        @init
        def build(self) -> None:
            self.app = answer

        @stop
        async def note(self) -> None:
            order.append("app")

    class One(asgi.Server):
        shared = dep(Shared)
        host = "127.0.0.1"
        port = 0

        @stop
        async def note(self) -> None:
            order.append("one")

    class Two(asgi.Server):
        shared = dep(Shared)
        host = "127.0.0.1"
        port = 0

        @stop
        async def note(self) -> None:
            order.append("two")

    class Both(Canary):
        one = dep(One)
        two = dep(Two)

    async with running(Both) as both:
        assert both.one.shared is both.two.shared
        assert both.one.port != both.two.port  # 一个进程，两个端口
    assert order.count("app") == 1
    assert order[-1] == "app"  # 两个服务器都停了之后才轮到它


async def test_the_real_process_has_two_ports_and_no_listener_at_the_root(relay) -> None:
    """``Server`` 不必是根单元：根上多一条 ``dep()`` 就是多一个端口。"""
    assert isinstance(relay.public, server.PublicServer)
    assert isinstance(relay.admin, server.AdminServer)
    assert unit(relay, Metrics) is relay.admin.metrics
    assert not isinstance(relay, asgi.Server)


# -- 在途请求的上限：类参数透传 uvicorn --------------------------------------


class Slow(asgi.App):
    """An application that takes 1.5s to answer."""

    path = "/"

    @init
    def build(self) -> None:
        self.app = self.serve

    async def serve(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        await asyncio.sleep(1.5)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


class Patient(asgi.Server):
    """No timeout configured: uvicorn waits for the in-flight request, however long."""

    slow = dep(Slow)
    host = "127.0.0.1"
    port = 0


class Impatient(asgi.Server, timeout_graceful_shutdown=1):
    """A bounded wait —— 类参数原样传给 ``uvicorn.Config``。"""

    slow = dep(Slow)
    host = "127.0.0.1"
    port = 0


async def _stop_while_a_request_is_in_flight(server_class: type[asgi.Server]) -> float:
    """Start, fire a slow request, stop, and report how long ``stop()`` took."""
    import httpx

    async with running(server_class) as server, httpx.AsyncClient() as client:
        call = asyncio.create_task(client.get(f"http://127.0.0.1:{server.port}/", timeout=20))
        await asyncio.sleep(0.2)
        began = time.monotonic()
        await server.stop()
        waited = time.monotonic() - began
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
    return waited


async def test_without_a_timeout_the_in_flight_request_holds_the_graph_open() -> None:
    """默认行为：uvicorn 的优雅停机等在途请求做完，``stop()` 就等那么久。

    上一轮这里是一条【毛病】——``Server`` 写死了 ``uvicorn.Config``，
    ``timeout_graceful_shutdown`` 没有入口，于是一个慢请求能把整张图的回收挂住，容器
    30s 之后 SIGKILL，``@stop`` 一个都不跑。现在它只是**默认值**，见下一条。
    """
    assert await _stop_while_a_request_is_in_flight(Patient) > 1.0


async def test_a_class_parameter_bounds_that_wait() -> None:
    """``class Impatient(asgi.Server, timeout_graceful_shutdown=1)`` —— 类参数透传 uvicorn。

    1.5s 的请求、1s 的预算：``stop()`` 到点就回收，不再无限等。``proxy_headers``、
    ``forwarded_allow_ips``、``access_log`` 这些也是同一条路（本场景的两个 Server 都带
    ``access_log=False``）。
    """
    waited = await _stop_while_a_request_is_in_flight(Impatient)
    assert 0.5 < waited < 1.4, f"等了 {waited:.2f}s"


async def test_the_real_servers_turn_the_access_log_off(relay) -> None:
    """压测时访问日志会严重干扰结果，所以两个端口都关掉了它。"""
    assert type(relay.public).__canary_server__["access_log"] is False
    assert type(relay.admin).__canary_server__["access_log"] is False


# -- 【毛病】port = 0 只在第一次成立 ---------------------------------------


async def test_restarting_a_server_reuses_the_port_it_was_given() -> None:
    """**【毛病】** ``@start`` 把实际端口写回 ``self.port``，所以重启时 ``port = 0`` 的
    语义丢了。

    文档说"``port = 0`` 由系统分配端口，开始服务后 ``server.port`` 是实际端口"。两件事
    用了同一个属性，于是第二次 ``start()`` 拿着上次分到的端口去绑——那个端口此时可能已经
    被别人占了，重启就失败。期望的行为是：请求的端口与实际端口分开（比如保留 ``port``，
    另给一个 ``bound_port``），或者 ``@stop`` 把 ``port`` 还原回去。
    """

    class Restartable(asgi.Server):
        echo = dep(Echo)
        host = "127.0.0.1"
        port = 0

    server = Restartable()
    await server.init()
    await server.start()
    first = server.port
    await server.stop()

    assert server.port == first  # 停下来之后仍然是上次分到的那个，不是 0

    squatter = socket.create_server(("127.0.0.1", first))
    try:
        with pytest.raises(OSError):
            await server.start()  # 期望：再分配一个新端口；实际：撞上占用
    finally:
        squatter.close()
        await server.stop()


async def test_restarting_a_server_works_when_the_port_is_free() -> None:
    """重启本身是成立的：``@start`` 会再跑，``@init`` 不会。

    这一条是上一条的另一半——``stop()`` 只把 ``start`` 和以它为前驱的阶段还原成空闲，
    ``init`` 仍然是"已进入"。所以在 ``@init`` 里建、在 ``@stop`` 里拆的东西，重启之后
    不会被重建。本场景的应用单元因此都把"可回收的资源"放在 ``@start``。
    """
    built: list[str] = []

    class Once(asgi.App):
        path = "/"

        @init
        def build(self) -> None:
            built.append("init")
            self.app = answer

    class Restartable(asgi.Server):
        once = dep(Once)
        host = "127.0.0.1"
        port = 0

    server = Restartable()
    async with server:
        first = server.port
    assert built == ["init"]

    async with server:  # 第二次：@start 再跑，@init 不再跑
        assert server.port == first
    assert built == ["init"]


# -- dispatch：路径怎么分发 ------------------------------------------------


def test_dispatch_matches_whole_segments_longest_first() -> None:
    hit: list[str] = []

    def app(name: str):
        async def application(scope, receive, send) -> None:
            hit.append(name)

        return application

    table = asgi.dispatch({"/": app("root"), "/api": app("api"), "/api/v2": app("v2")})

    async def call(path: str) -> None:
        await table({"type": "http", "path": path}, None, None)

    asyncio.run(call("/api"))
    asyncio.run(call("/api/books"))
    asyncio.run(call("/api/v2/books"))
    asyncio.run(call("/apix"))
    asyncio.run(call("/"))
    assert hit == ["api", "api", "v2", "root", "root"]


def test_dispatch_normalises_trailing_slashes_and_refuses_duplicates() -> None:
    async def app(scope, receive, send) -> None:
        pass

    with pytest.raises(ValueError, match="given twice"):
        asgi.dispatch({"/api": app, "/api/": app})
    with pytest.raises(ValueError, match="must start with"):
        asgi.dispatch({"api": app})


async def test_dispatch_says_nothing_to_a_lifespan_scope() -> None:
    """**【毛病】** ``dispatch`` 收到 ``lifespan`` 的 scope 时直接返回，一条消息都不送。

    框架自己的 ``Server`` 用 ``lifespan="off"``，所以进程里碰不到；但 ``dispatch`` 是
    **公开导出**的函数，拿它拼出来的应用交给任何会驱动 lifespan 的东西（Starlette 的
    ``TestClient``、``uvicorn --lifespan on``、``asgi-lifespan``），对方就会一直等
    ``lifespan.startup.complete``。期望的行为是回一条 ``complete``（或者明确地
    ``failed``），而不是沉默。
    """
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    async def send(message: dict) -> None:
        sent.append(message)

    async def app(scope, receive, send) -> None:
        raise AssertionError("不该被调用")

    table = asgi.dispatch({"/": app})
    await asyncio.wait_for(table({"type": "lifespan"}, receive, send), timeout=2)
    assert sent == []  # 期望: [{"type": "lifespan.startup.complete"}]


async def test_dispatch_refuses_an_unmatched_websocket() -> None:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    table = asgi.dispatch({"/ws": lambda *_: None})
    await table({"type": "websocket", "path": "/other"}, None, send)
    assert sent == [{"type": "websocket.close", "code": 1008}]


# -- 配置：单元化的 Settings ------------------------------------------------


class FakeSecrets(SecretStore):
    """A double for the secret file —— 替身必须是被替换类型的实例。"""

    def read(self, name: str) -> str:
        return f"fake-{name}"


async def test_settings_can_have_dependencies_and_hooks() -> None:
    """``config`` 文档的承诺：``dep()`` 写在模型里不是字段，``@init`` 可以补字段的值。"""
    assert "secrets" not in AdminSettings.model_fields

    async with running(AdminSettings, {SecretStore: FakeSecrets()}) as settings:
        assert settings.token == "fake-admin-token"


async def test_two_settings_units_read_their_own_prefixes(monkeypatch) -> None:
    """一个进程里多份配置，就是多个单元：各读自己的 ``env_prefix``，共享同一个 ``.env``。"""
    monkeypatch.setenv("RELAY_SITE_ID", "shop-042")
    monkeypatch.setenv("RELAY_PORT", "18020")
    monkeypatch.setenv("ADMIN_PORT", "19020")
    monkeypatch.setenv("ADMIN_TOKEN", "from-env")

    edge = EdgeSettings()
    admin = AdminSettings()
    assert (edge.site_id, edge.port) == ("shop-042", 18020)
    assert (admin.port, admin.token) == (19020, "from-env")
    # 前缀不串门：ADMIN_PORT 没有变成 EdgeSettings.port
    assert edge.port != admin.port


async def test_a_settings_double_replaces_it_across_the_whole_graph(relay) -> None:
    """替身走 ``provide``，所以整张图拿到的是同一份被换过的配置。"""
    assert unit(relay, EdgeSettings).site_id == "test-site"
    assert relay.public.config is unit(relay, EdgeSettings)
    assert unit(relay, Fleet).config is relay.public.config


# -- 测试辅助本身 ----------------------------------------------------------


async def test_unit_before_the_lifecycle_raises(relay) -> None:
    """图在第一次进入生命周期时才建立。"""
    fresh = root_class("fastapi")()
    with pytest.raises(LookupError):
        unit(fresh, Fleet)


async def test_a_double_of_the_wrong_type_is_refused_before_anything_starts() -> None:
    started: list[str] = []

    class Watcher(Canary):
        clock = dep(Clock)

        @init
        def note(self) -> None:
            started.append("init")

    with pytest.raises(TypeError):
        async with running(Watcher, {Clock: object()}):  # type: ignore[dict-item]
            pass
    assert started == []  # 任何单元启动之前就失败了


async def test_providing_after_the_lifecycle_began_is_refused(relay) -> None:
    with pytest.raises(LifecycleError, match="already has"):
        scope_of(relay).provide(Clock, Clock())

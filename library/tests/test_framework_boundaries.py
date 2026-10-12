"""Executable notes on running an HTTP application as part of the graph.

上一版这里钉的是 Canary ↔ FastAPI 的接缝：两层生命周期怎么对接、请求怎么拿到单元。换成
``canary_framework.asgi`` 之后接缝没有了——应用、路由、监听都是图上的单元——所以这个文件
现在钉的是：监听是生命周期的一部分、启动失败时的表现、领域异常怎么落地、替身怎么换，
以及框架仍然不提供的东西。

**这些断言对两层 HTTP 都成立**，所以这个文件跑两遍（``conftest.py`` 的 ``stack``）。
只属于某一层的东西在 ``test_stack_fastapi.py`` / ``test_stack_web.py``。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from canary_framework import Canary, LifecycleError, dep, scope_of, start, stop
from canary_framework.test import running, unit

from app.api import application
from app.common.errors import ConflictError, NotFoundError, ValidationError
from app.infra.db import Database
from app.testing import listener, make_book, make_reader
from config import AppConfig


@pytest.fixture
def gateway(stack):
    """A ``Gateway`` of the current stack, with ``port = 0``.

    两层各有一个 ``Gateway``：``dep()`` 是写在类上的声明，所以"听哪个应用"只能由类决定。
    ``app.testing.listener`` 就是按栈取一个、把端口换成 0。
    """
    return listener(stack)


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class Acquires(Canary):
    """A unit that acquires something in ``@start`` and gives it back in ``@stop``."""

    log: list[str] = []

    @start
    async def take(self) -> None:
        self.log.append("acquired")

    @stop
    async def give_back(self) -> None:
        self.log.append("released")


class Broken(Canary):
    """A unit whose ``@start`` fails, after its dependency has already started."""

    acquires = dep(Acquires)

    @start
    async def fail(self) -> None:
        raise RuntimeError("连不上数据库")


# --- 监听是生命周期的一部分 -------------------------------------------------


async def test_the_server_listens_between_start_and_stop(gateway):
    """``@start`` 绑定端口并开始服务，``@stop`` 关闭——走的是真实的套接字。"""
    async with running(gateway) as gateway:
        assert gateway.port != 0, "port = 0 由系统分配，开始服务后回写实际端口"
        url = f"http://127.0.0.1:{gateway.port}/api/health"
        async with httpx.AsyncClient() as http:
            assert (await http.get(url)).status_code == 200
        assert unit(gateway, Database).engine is not None
        assert scope_of(gateway).entered(start), "start 台账上记着每个已启动的单元"

    # 回收按台账逆序进行，完成后台账被排空——这是"整张图确实回收过"的证据
    assert not scope_of(gateway).entered(start)
    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectError):
            await http.get(url)


async def test_a_startup_failure_never_opens_the_port(gateway):
    """图起不来就不该开始服务：监听的单元依赖所有人，所以它最后启动，轮不到它。

    已经拿到的资源照常回收，异常原样抛出——和守护进程场景共用同一条"失败也走 stop()"
    的回收路径，不再依赖 uvicorn 怎么处理 lifespan 失败。
    """
    Acquires.log = released = []
    # 加一条依赖就要一个新类：图是静态的，所以这里现做一个 Gateway 的子类。
    doomed = type("Doomed", (gateway,), {"broken": dep(Broken)})()
    with pytest.raises(RuntimeError, match="连不上数据库"):
        async with doomed:
            pass
    assert released == ["acquired", "released"]
    assert doomed.port == 0, "从未绑定过端口"


async def test_a_port_in_use_fails_the_start_and_reclaims_the_graph(gateway):
    """端口被占用是普通的启动失败：抛 ``OSError``，已启动的数据库照常回收。"""
    async with running(gateway) as first:
        second = type("Second", (gateway,), {"port": first.port})()
        with pytest.raises(OSError):
            async with second:
                pass
        assert not scope_of(second).entered(start)


async def test_the_graph_is_built_once_not_per_request(client, root):
    """作用域的粒度是一次运行，不是一次请求——这正是连接池该有的粒度。"""
    engine = unit(root, Database).engine
    first = await client.get("/api/health")
    second = await client.get("/api/health")
    assert first.json() == second.json()
    assert unit(root, Database).engine is engine


async def test_concurrent_requests_share_one_graph(client):
    """并发请求不会各自建图，也不会把半张图暴露出去。"""
    answers = await asyncio.gather(*(client.get("/api/health") for _ in range(8)))
    assert [answer.status_code for answer in answers] == [200] * 8


# --- 接口怎么拿到单元 -------------------------------------------------------


async def test_an_endpoint_uses_the_very_instance_from_the_graph(client, root):
    from app.module.catalog.service import CatalogService

    body = (await client.get("/api/health")).json()["data"]
    assert body["dialect"] == unit(root, Database).dialect
    # 路由单元上的依赖就是图里那一个，不是新造的
    assert root.api.catalog.catalog is unit(root, CatalogService)
    assert unit(root, CatalogService).database is unit(root, Database)


async def test_a_domain_error_is_an_ordinary_exception_without_http(root):
    """不经 HTTP 调接口方法，领域异常就是普通异常——信封是应用单元加上去的。"""
    with pytest.raises(NotFoundError):
        await root.api.catalog.get_book("bk_does_not_exist")


def test_reading_a_dependency_outside_the_lifecycle_is_refused():
    """依赖从 ``@init`` 起才可用；在 ``__init__`` 里读会抛 ``LifecycleError``。"""

    class TooEager(Canary):
        database = dep(Database)

        def __init__(self) -> None:
            self.stolen = self.database

    with pytest.raises(LifecycleError, match="before the lifecycle begins"):
        asyncio.run(TooEager().init())


# --- 领域异常落地 -----------------------------------------------------------


async def test_a_domain_error_lands_on_both_the_status_line_and_the_envelope(client):
    """一处异常处理器，全部路由生效。"""
    response = await client.get("/api/catalog/books/bk_does_not_exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 404
    assert body["data"] is None
    assert "不存在" in body["msg"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(NotFoundError, 404), (ConflictError, 409), (ValidationError, 422)],
)
def test_every_domain_error_class_maps_to_its_status(error, status):
    assert error("x").code == status


async def test_a_conflict_is_reported_as_409(client):
    book = await make_book(client, isbn="978-7-111-00000-1")
    again = await client.post(
        "/api/catalog/books",
        json={"title": "重复", "author": "x", "isbn": "978-7-111-00000-1"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == 409
    assert book["isbn"] == "978-7-111-00000-1"


async def test_a_request_body_that_fails_validation_is_422_before_any_service_runs(client):
    """绑定失败由 HTTP 层处理，服务层根本不会被调用。

    两层的报文格式都是 ``{"detail": [...]}``——pydantic 的错误列表，不是领域信封。巧合吗？
    不是：``asgi.web`` 的 422 刻意按 FastAPI 的形状来，所以换一层 HTTP 客户端不用改。
    """
    response = await client.post("/api/catalog/books", json={"title": "缺作者"})
    assert response.status_code == 422
    assert "detail" in response.json(), "这是校验错误的格式，不是领域信封"


# --- 替换：running 的第二个参数 ---------------------------------------------


async def test_a_double_replaces_the_real_config_before_anything_starts(stack):
    """整张图跑在测试给的配置上，真配置连构造都不会发生。"""
    doubles = {AppConfig: AppConfig(embedding_dim=64, chunk_size=99)}
    async with running(application(stack), doubles) as root:
        assert unit(root, AppConfig).embedding_dim == 64
        assert unit(root, Database).config.chunk_size == 99
        assert unit(root, AppConfig).storage == "sqlite"


def test_a_provided_substitute_keeps_the_real_unit_from_being_constructed():
    """0.9.x 的 ``setattr`` 缝做不到这点：被替掉的那棵子树照样实例化、照样启动。"""
    built: list[str] = []

    class Expensive(Canary):
        def __init__(self) -> None:
            built.append("constructed")

        @start
        async def connect(self) -> None:
            built.append("connected")

    class Fake(Expensive):
        def __init__(self) -> None:
            pass

        @start
        async def connect(self) -> None:
            built.append("fake connected")

    class Service(Canary):
        expensive = dep(Expensive)

    async def run() -> None:
        service = Service()
        scope_of(service).provide(Expensive, Fake())
        async with service:
            assert isinstance(service.expensive, Fake)

    asyncio.run(run())
    assert built == ["fake connected"]


# --- 框架仍然不提供的东西 ---------------------------------------------------


def test_there_is_no_request_scope():
    """作用域是一次运行，没有请求级实例——所以工作单元由 service 自己开。

    这不是缺陷，是范围：框架不认识"请求"这个概念了。代价是每个写库的方法都要记得
    ``async with self.database.begin()``。
    """
    assert not any("request" in name.lower() for name in vars(Canary))
    assert {n for n in vars(Canary) if not n.startswith("_")} == {"init", "start", "stop"}


def test_there_is_no_background_task_facility():
    """建索引因此是同步的——见 ``app/module/rag/service.py`` 的说明。

    场景二自带了一份 ``SupervisedTasks``；两个场景各写一次，这笔账记在这里。
    """
    public = {n for n in vars(Canary) if not n.startswith("_")}
    assert not any(k in n for n in public for k in ("task", "background", "job"))


# --- 框架做对的部分（回归保护） ---------------------------------------------


def test_stop_is_idempotent_and_reclaims_only_once():
    log: list[str] = []

    class Unit(Canary):
        @stop
        async def t(self) -> None:
            log.append("stop")

    async def run() -> None:
        u = Unit()
        async with u:
            pass
        await u.stop()
        await u.stop()

    asyncio.run(run())
    assert log == ["stop"]


async def test_the_whole_flow_still_works_end_to_end(client):
    """接缝换了，业务不该有感——一次完整的借书流程。"""
    book = await make_book(client)
    reader = await make_reader(client)
    loan = await client.post(
        "/api/circulation/borrow",
        json={"book_id": book["id"], "reader_id": reader["id"]},
    )
    assert loan.status_code == 200, loan.text
    assert loan.json()["code"] == 0

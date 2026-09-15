"""Executable notes on the Canary ↔ FastAPI seam, from the request-driven side.

0.10.0 删掉了 ``canary_framework.web``。框架只剩依赖注入与生命周期，web 那一半换成了
FastAPI。这个文件钉住接缝本身：两层生命周期怎么对接、请求怎么拿到单元、领域异常怎么
落地、以及接缝在失败时的表现。

上一版这里钉的是框架自带 web 层的六个缺陷（请求体失败路径、冷启动并发、返回值校验、
两个 body 形参、路由静默丢失、prefix 缺斜杠）。那一层不存在了，对应的断言换成
"FastAPI 在同样的位置是什么行为"——因为选型换了，这些问题不会消失，只是换了归属。
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from canary_framework import Canary, LifecycleError, dep, scope_of, start, stop
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from app.api import create_app
from app.common.errors import ConflictError, NotFoundError, ValidationError
from app.composition import LibraryApi
from app.infra.db import Database
from app.testing import make_book, make_reader, seed, unit
from config import AppConfig

# --- 两层生命周期的对接 -----------------------------------------------------


def test_lifespan_starts_and_stops_the_whole_graph():
    """``TestClient`` 的上下文管理器驱动 ASGI lifespan，lifespan 驱动 Canary。"""
    app = create_app()
    with TestClient(app) as client:
        root = client.app.state.root
        assert unit(root, Database).engine is not None
        assert client.get("/api/health").status_code == 200
        assert scope_of(root).entered["start"], "start 台账上记着每个已启动的单元"

    # 回收按台账逆序进行，完成后台账被排空——这是"整张图确实回收过"的证据
    assert scope_of(root).entered["start"] == []


def test_a_startup_failure_prevents_the_app_from_serving():
    """图起不来，应用就不该开始服务——lifespan 把异常原样抛给 ASGI 服务器。

    这是守护进程场景与 HTTP 场景在框架上的分水岭：那边失败要自己回收，这边由
    uvicorn/TestClient 直接放弃启动。两边共用的是同一条"失败也走 stop()"的回收路径。
    """
    released: list[str] = []

    class Acquires(Canary):
        @start
        async def s(self) -> None:
            released.append("acquired")

        @stop
        async def t(self) -> None:
            released.append("released")

    class Broken(Canary):
        acquires = dep(Acquires)

        @start
        async def s(self) -> None:
            raise RuntimeError("连不上数据库")

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with Broken():
            yield

    app = FastAPI(lifespan=lifespan)
    with pytest.raises(RuntimeError, match="连不上数据库"), TestClient(app):
        pass
    # 关键：已经拿到的资源被回收了，没有泄漏
    assert released == ["acquired", "released"]


def test_the_graph_is_built_once_not_per_request(client, root):
    """作用域的粒度是一次运行，不是一次请求——这正是连接池该有的粒度。"""
    first = client.get("/api/health")
    second = client.get("/api/health")
    assert first.json() == second.json()
    assert client.app.state.root is root


def test_concurrent_requests_share_one_graph(client, root):
    """并发请求不会各自建图，也不会把半张图暴露出去。"""
    seen: list[int] = []
    errors: list[BaseException] = []

    def hit() -> None:
        try:
            seen.append(client.get("/api/health").status_code)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert seen == [200] * 8


# --- 请求怎么拿到单元 -------------------------------------------------------


def test_a_handler_receives_the_very_instance_from_the_graph(client, root):
    from app.module.catalog.service import CatalogService

    body = client.get("/api/health").json()["data"]
    assert body["dialect"] == unit(root, Database).dialect
    # handler 拿到的就是图里那一个，不是新造的
    assert unit(root, CatalogService).database is unit(root, Database)


def test_reading_a_dependency_outside_the_lifecycle_is_refused():
    """依赖从 ``@init`` 起才可用；在 ``__init__`` 里读会抛 ``LifecycleError``。"""

    class TooEager(Canary):
        database = dep(Database)

        def __init__(self) -> None:
            self.stolen = self.database

    with pytest.raises(LifecycleError, match="before the lifecycle begins"):
        asyncio.run(TooEager().init())


# --- 领域异常落地 -----------------------------------------------------------


def test_a_domain_error_lands_on_both_the_status_line_and_the_envelope(client):
    """一处异常处理器，全部路由生效——0.9.x 要每个 handler 自己记得接。"""
    response = client.get("/api/catalog/books/bk_does_not_exist")
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


def test_a_conflict_is_reported_as_409(client):
    book = make_book(client, isbn="978-7-111-00000-1")
    again = client.post(
        "/api/catalog/books",
        json={"title": "重复", "author": "x", "isbn": "978-7-111-00000-1"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == 409
    assert book["isbn"] == "978-7-111-00000-1"


def test_a_request_body_that_fails_validation_is_422_before_any_service_runs(client):
    """绑定失败由 FastAPI 处理，服务层根本不会被调用。"""
    response = client.post("/api/catalog/books", json={"title": "缺作者"})
    assert response.status_code == 422
    assert "detail" in response.json(), "这是 FastAPI 的校验错误格式，不是领域信封"


class Guarded(BaseModel):
    """必须定义在模块层：``get_type_hints`` 看不见函数局部作用域。"""

    left: int | None = None
    right: int | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Guarded:
        if self.left is None and self.right is None:
            raise ValueError("left / right 至少提供一个")
        return self


def test_a_model_validator_failure_is_also_422(client):
    """跨字段校验和单字段校验走同一条路。"""
    app = FastAPI()

    @app.post("/guarded")
    async def guarded(item: Guarded) -> dict:  # noqa: ARG001
        return {"ok": True}

    with TestClient(app) as c:
        assert c.post("/guarded", json={}).status_code == 422
        assert c.post("/guarded", json={"left": 1}).status_code == 200


def test_a_real_bug_is_not_disguised_as_a_domain_error():
    """只有 ``DomainError`` 走信封；真 bug 照常冒泡，不会被当成业务失败。"""
    from app.common.errors import DomainError
    from app.wiring import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/bug")
    async def bug() -> dict:
        raise ZeroDivisionError("这是真 bug")

    @app.get("/domain")
    async def domain() -> dict:
        raise DomainError("这是业务失败", 400)

    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/bug").status_code == 500
        answer = c.get("/domain")
        assert answer.status_code == 400
        assert answer.json()["code"] == 400


def test_constraints_in_the_schema_are_enforced(client):
    """``Field(ge=..., le=...)`` 由 FastAPI 强制，服务层不必重复校验。"""
    response = client.post(
        "/api/catalog/books",
        json={"title": "x", "author": "y", "copies": 999},  # le=100
    )
    assert response.status_code == 422


# --- 替换缝：没有 provide=，但作用域可以预登记 -------------------------------


def test_a_seeded_config_replaces_the_real_one_before_anything_starts():
    """整张图跑在测试给的配置上，真配置连构造都不会发生。"""

    async def run() -> str:
        root = LibraryApi()
        seed(scope_of(root), AppConfig, AppConfig(embedding_dim=64, chunk_size=99))
        async with root:
            assert unit(root, AppConfig).embedding_dim == 64
            assert unit(root, Database).config.chunk_size == 99
            return unit(root, AppConfig).storage

    assert asyncio.run(run()) == "sqlite"


def test_a_seeded_substitute_keeps_the_real_unit_from_being_constructed():
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
        seed(scope_of(service), Expensive, Fake())
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


def test_the_whole_flow_still_works_end_to_end(client):
    """接缝换了，业务不该有感——一次完整的借书流程。"""
    book = make_book(client)
    reader = make_reader(client)
    loan = client.post(
        "/api/circulation/borrow",
        json={"book_id": book["id"], "reader_id": reader["id"]},
    )
    assert loan.status_code == 200, loan.text
    assert loan.json()["code"] == 0

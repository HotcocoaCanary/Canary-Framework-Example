"""Executable notes on Canary's web surface — 最终版（`release/0.9.3` @ `322315e`）。

上一轮在这里钉住了六个 web 侧缺陷（#022 请求体失败路径、#026 冷启动并发、
#027 返回值不校验、#029 两个 body 形参、#031 路由静默丢失、#033 prefix 缺斜杠）。
**六个全修好了**，所以每一个都从另一侧重新钉住：退回去，这里就会红。

一并记下最终版删掉的东西（``provide=``、``@on_request_error``、嵌套前缀、
``Query``/``Path``/``Body`` 标记）与补上的东西（``status_code``、``tags``、
``Annotated`` 里的约束）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Annotated

import httpx
import pytest
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.testclient import TestClient

from canary_framework import Canary, cocoa, on_start
from canary_framework.common.error import DeclarationError, InjectionError
from canary_framework.core.infra.naming import to_snake
from canary_framework.web import (
    Cookie,
    HTTPError,
    Header,
    RouteRegistrationError,
    delete,
    get,
    post,
    web_cocoa,
)


class Item(BaseModel):
    a: int


class GuardedItem(BaseModel):
    left: int | None = None
    right: int | None = None

    @model_validator(mode="after")
    def _one_of(self) -> GuardedItem:
        if self.left is None and self.right is None:
            raise ValueError("left / right 至少提供一个")
        return self


class Bounded(BaseModel):
    n: int


class Out(BaseModel):
    """必须定义在模块层：``get_type_hints`` 看不见函数局部作用域。"""

    a: int


class ToyDomainError(Exception):
    """A domain error that knows nothing about HTTP."""


@web_cocoa(prefix="/toy", title="Toy API", version="0.1.0")
class Toy:
    seen: list[str]

    @on_start
    async def prepare(self) -> None:
        self.seen = []

    @get("/bug")
    async def bug(self) -> str:
        raise ZeroDivisionError("这是真 bug")

    @get("/domain")
    async def domain(self) -> str:
        raise ToyDomainError("图书不存在")

    @get("/teapot")
    async def teapot(self) -> str:
        raise HTTPError(418, "I'm a teapot", headers={"X-Brew": "no"})

    @get("/plain")
    async def plain(self) -> Response:
        return PlainTextResponse("hello")

    @get("/stream")
    async def stream(self) -> Response:
        async def chunks():
            yield b"data: 1\n\n"
            yield b"data: 2\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    @get("/created")
    async def created(self) -> Response:
        return JSONResponse({"ok": True}, status_code=201, headers={"Location": "/toy/1"})

    @get("/deferred")
    async def deferred(self) -> Response:
        async def after() -> None:
            self.seen.append("background ran")

        return JSONResponse({"queued": True}, background=BackgroundTask(after))

    @post("/guarded")
    async def guarded(self, item: GuardedItem) -> dict:
        return {"ok": True}

    @post("/bounded")
    async def bounded(self, item: Bounded) -> dict:
        return {"n": item.n}

    @post("/items")
    async def create(self, item: Item) -> dict:
        return {"a": item.a}

    @post("/raw")
    async def raw(self, body: dict) -> dict:
        """A bare ``dict`` — 0.9.2 called this a missing *query* parameter."""
        return {"keys": sorted(body)}

    @post("/batch")
    async def batch(self, items: list[Item]) -> dict:
        return {"count": len(items)}

    @get("/tree/{sub:path}")
    async def tree(self, sub: str) -> str:
        return sub

    @get("/tags")
    async def tags(self, tag: list[str]) -> dict:
        return {"tags": tag}

    @get("/whoami")
    async def whoami(
        self,
        x_token: Annotated[str, Header()] = "anonymous",
        sid: Annotated[str, Cookie(alias="session")] = "none",
    ) -> dict:
        return {"token": x_token, "sid": sid}

    @get("/echo")
    async def echo(self, request: Request) -> dict:
        return {"path": request.url.path}


@pytest.fixture
def toy():
    app = Canary(Toy)
    with TestClient(app) as client:
        client.canary_instance = app[Toy]
        yield client


# --- 早先版本的缺陷，现在从另一侧钉住 ------------------------------------


def test_a_sync_handler_is_refused_at_declaration_time():
    """#004 —— 同步 handler 不再静默阻塞事件循环，而是根本注册不上。

    拒绝发生在 ``@get`` 求值的那一刻，也就是 **import 时**：错误离现场最近，
    代价是一个同步 handler 会让整个模块 import 失败。
    """
    with pytest.raises(RouteRegistrationError, match="not an async function"):

        @web_cocoa
        class Blocking:
            @get("/slow")
            def slow(self) -> str:
                return "slow"


def test_async_handlers_no_longer_serialise_the_process():
    """#004 的另一半：显式让出之后，并发的阻塞调用不再串行。"""

    @web_cocoa
    class Offloaded:
        @get("/slow")
        async def slow(self) -> str:
            await asyncio.to_thread(time.sleep, 0.2)
            return "slow"

    async def scenario() -> float:
        app = Canary(Offloaded)
        await app.init()
        await app.start()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            started = time.perf_counter()
            await asyncio.gather(*[client.get("/slow") for _ in range(4)])
            elapsed = time.perf_counter() - started
        await app.stop()
        return elapsed

    assert asyncio.run(scenario()) < 0.6


def test_an_unmapped_exception_is_a_json_500(toy):
    """#002 的兜底：没接住的异常不再裸奔出 ASGI 应用，而是 JSON 500。

    ``raise_server_exceptions=False`` 是必须的——Starlette 的 ServerErrorMiddleware
    在写完响应后仍会重新抛出，好让 traceback 进服务器日志。
    """
    with TestClient(Canary(Toy), raise_server_exceptions=False) as client:
        response = client.get("/toy/bug")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal Server Error"}


def test_a_domain_error_now_has_exactly_one_way_out(toy):
    """``@on_request_error`` 被删：领域异常抛出去只剩 500，映射必须由应用自己做。

    本项目因此把映射收在 ``app.common.errors.ok()`` 里——每个 handler 都要过它。
    这是 HEAD 的设计选择（"异常只剩三条固定出路"），钉在这里是为了让它变回
    可映射时有测试提醒。
    """
    with TestClient(Canary(Toy), raise_server_exceptions=False) as client:
        response = client.get("/toy/domain")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}


def test_http_error_needs_no_registration(toy):
    """``HTTPError`` 是纯 HTTP 概念的错误，内置处理，headers 也带出去。"""
    response = toy.get("/toy/teapot")
    assert response.status_code == 418
    assert response.json() == {"detail": "I'm a teapot"}
    assert response.headers["X-Brew"] == "no"


def test_a_validator_error_renders_a_real_422(toy):
    """#003 —— validator 抛 ValueError 时 422 自身不再崩成 500。"""
    response = toy.post("/toy/guarded", json={})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "left / right 至少提供一个" in json.dumps(detail, ensure_ascii=False)
    assert toy.post("/toy/items", json={"a": "не число"}).status_code == 422


def test_the_422_payload_keeps_constraint_values(toy):
    """约束值仍然保留——这是客户端定位问题的依据。"""
    response = toy.post("/toy/bounded", json={"n": "abc"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "int_parsing"


def test_a_handler_may_return_a_response(toy):
    """#005 —— Response 原样放行：纯文本、SSE、自定义状态码与响应头。"""
    plain = toy.get("/toy/plain")
    assert plain.status_code == 200
    assert plain.text == "hello"
    assert plain.headers["content-type"].startswith("text/plain")

    stream = toy.get("/toy/stream")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.text == "data: 1\n\ndata: 2\n\n"

    created = toy.get("/toy/created")
    assert created.status_code == 201
    assert created.headers["Location"] == "/toy/1"


def test_a_background_task_hung_on_the_response_runs(toy):
    """#010 的一半：请求返回之后还能干活了（进程内，非持久队列）。"""
    assert toy.get("/toy/deferred").json() == {"queued": True}
    assert toy.canary_instance.seen == ["background ran"]


def test_a_non_scalar_parameter_is_read_from_the_body(toy):
    """POST 一个 ``dict`` / ``list[Model]`` 不再得到 "missing query parameter"。"""
    assert toy.post("/toy/raw", json={"b": 2, "a": 1}).json() == {"keys": ["a", "b"]}
    assert toy.post("/toy/batch", json=[{"a": 1}, {"a": 2}]).json() == {"count": 2}


def test_the_path_converter_no_longer_leaks_into_the_document(toy):
    """#008 —— ``{sub:path}`` 归一化为 ``{sub}``，客户端生成器能对上了。"""
    assert toy.get("/toy/tree/a/b/c").json() == "a/b/c"
    paths = toy.get("/openapi.json").json()["paths"]
    assert "/toy/tree/{sub}" in paths
    assert "/toy/tree/{sub:path}" not in paths


def test_one_unschemable_type_no_longer_takes_the_whole_document_down(caplog):
    """#001 —— 生成不出 schema 的类型退化成"未约束"并记 WARNING。

    HEAD 把这条 WARNING 从"第一次请求"提前到了**装配期**：签名在启动时就编译，
    所以 logger 也从 ``canary.web.openapi`` 变成了 ``canary.web``。
    """

    @web_cocoa
    class Mixed:
        @get("/fine")
        async def fine(self) -> Item:
            return Item(a=1)

        @get("/weird")
        async def weird(self) -> threading.Lock:  # 无法生成 schema
            raise NotImplementedError

    with caplog.at_level(logging.WARNING, logger="canary.web"):
        with TestClient(Canary(Mixed)) as client:
            doc = client.get("/openapi.json")

    assert doc.status_code == 200
    paths = doc.json()["paths"]
    assert paths["/fine"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert paths["/weird"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {}
    assert any("no schema for" in r.getMessage() for r in caplog.records)
    assert any(r.name == "canary.web" for r in caplog.records), "WARNING 现在出自装配期"


def test_there_is_no_substitution_entry_left():
    """``provide=`` 被删：``Canary`` 只收根，图上的实例全部由框架无参构造。

    这是最终版最大的一处收窄。框架的理由是"单元从哪来"只该有一个答案，而
    ``provide`` 与"必须能无参构造"这条规则一直在互咬（旧 #024）。
    代价记在 doc/verification-final.md：本项目因此把"用哪个模型实现"退回单元内部
    的配置分支（`app/infra/ai.py`），那正是 0.9.3 的 ``overrides=`` 曾经删掉的写法。
    """
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        Canary(Toy, provide={Toy: object()})  # type: ignore[call-arg]

    # 单元测试仍然做得到——注入只是 setattr，一行就能替：
    @cocoa
    class Engine:
        async def run(self) -> str:
            return "real"

    @cocoa(deps=[Engine])
    class Uses:
        engine: Engine

    class FakeEngine:
        async def run(self) -> str:
            return "fake"

    async def scenario() -> str:
        app = Canary(Uses)
        await app.init()  # 注入发生在这里，@on_start 还没跑
        app[Uses].engine = FakeEngine()  # type: ignore[assignment]
        await app.start()
        result = await app[Uses].engine.run()
        await app.stop()
        return result

    assert asyncio.run(scenario()) == "fake"
    # 但替身的 @on_start / @on_stop 不会被执行——它不在图上，框架不知道它存在。


def test_two_sources_claiming_one_attribute_now_raise():
    """#007 —— snake_case 撞名不再"后写的赢"，而是装配期报错。"""
    assert to_snake("KBFileRepository") == to_snake("KbFileRepository") == "kb_file_repository"

    @cocoa
    class KBFileRepository:
        pass

    @cocoa
    class KbFileRepository:
        pass

    @cocoa(deps=[KBFileRepository, KbFileRepository])
    class Both:
        pass

    with pytest.raises(InjectionError, match="kb_file_repository"):
        asyncio.run(Canary(Both).init())


def test_a_startup_failure_now_reaches_the_caller():
    """#019 修好了：``lifespan.startup.failed`` 之后框架把异常抛出去。

    0.9.3 里发完消息就 ``return``，于是 ``TestClient`` 认为应用起来了，退出
    ``with`` 时永久挂起。现在照 Starlette 自己的 ``Router.lifespan`` 办：先如实
    汇报，再 ``raise``——调用方靠那个异常才知道失败。
    """

    @web_cocoa
    class Broken:
        @on_start
        async def boom(self) -> None:
            raise RuntimeError("启动失败")

        @get("/ping")
        async def ping(self) -> str:
            return "pong"

    done = threading.Event()
    caught: list[BaseException] = []

    def drive() -> None:
        try:
            with TestClient(Canary(Broken)):
                pass
        except BaseException as exc:  # noqa: BLE001 —— 正是我们想看到的那个异常
            caught.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    worker.join(timeout=10)

    assert done.is_set(), "启动失败又把调用方挂住了"
    assert caught and isinstance(caught[0], RuntimeError)
    assert "启动失败" in str(caught[0])


# --- HEAD 新的收窄：钉住它们，免得悄悄变回去 ------------------------------


def test_a_prefix_is_absolute_and_does_not_nest():
    """0.9.2 的嵌套前缀被删：``prefix`` 与"谁依赖我"无关。"""

    @web_cocoa(prefix="/admin")
    class Admin:
        @get("/dashboard")
        async def dashboard(self) -> str:
            return "admin"

    @web_cocoa(prefix="/api", deps=[Admin])
    class Api:
        admin: Admin

        @get("/users")
        async def users(self) -> str:
            return "users"

    with TestClient(Canary(Api)) as client:
        assert client.get("/api/users").json() == "users"
        assert client.get("/admin/dashboard").json() == "admin"
        assert client.get("/api/admin/dashboard").status_code == 404


def test_only_header_and_cookie_have_markers_and_only_inside_annotated(toy):
    """来源标记只剩两个，写法只剩一种。"""
    response = toy.get("/toy/whoami", headers={"x-token": "T"}, cookies={"session": "S"})
    assert response.json() == {"token": "T", "sid": "S"}
    assert toy.get("/toy/whoami").json() == {"token": "anonymous", "sid": "none"}

    with pytest.raises(RouteRegistrationError, match="Source markers go in the annotation"):

        @web_cocoa
        class OldStyle:
            @get("/x")
            async def x(self, token: str = Header()) -> str:  # 0.9.3 的 FastAPI 写法
                return token


def test_inference_covers_the_rest(toy):
    """标量走 query（命中占位符则 path），``list[标量]`` 走 query 多值，其余走 body。"""
    assert toy.get("/toy/tags?tag=a&tag=b").json() == {"tags": ["a", "b"]}
    assert toy.get("/toy/echo").json() == {"path": "/toy/echo"}
    assert toy.get("/toy/tags").status_code == 422  # 缺必填查询参数


def test_duplicate_routes_are_caught_at_assembly_time():
    @web_cocoa
    class Left:
        @get("/dup")
        async def left(self) -> str:
            return "l"

    @web_cocoa(deps=[Left])
    class Right:
        left: Left

        @get("/dup")
        async def right(self) -> str:
            return "r"

    app = Canary(Right)
    asyncio.run(app.init())
    with pytest.raises(RouteRegistrationError, match="duplicate route"):
        asyncio.run(app.start())


def test_mixins_with_identically_named_handlers_both_register():
    class ListMixin:
        @get("/mixin/list")
        async def listing(self) -> str:
            return "mixin"

    @web_cocoa
    class Combined(ListMixin):
        @get("/own/list")
        async def own_listing(self) -> str:
            return "own"

    with TestClient(Canary(Combined)) as client:
        assert client.get("/mixin/list").json() == "mixin"
        assert client.get("/own/list").json() == "own"


# --- 上一轮的六个缺陷，现在从另一侧钉住 ------------------------------------


def test_every_body_failure_is_now_a_422():
    """#022 修好了：请求体的三条失败路径 + "可选请求体"。

    从前 ``await request.json()`` 抛的 ``JSONDecodeError`` 不在捕获范围里，
    四种客户端错误全变成 500 加一条服务端 traceback。现在先读原始字节再解析，
    "没有请求体"和"请求体是 null"也分得开了。
    """

    @web_cocoa
    class API:
        @post("/items")
        async def create(self, item: Item) -> dict:
            return {"a": item.a}

        @post("/optional")
        async def optional(self, item: Item | None = None) -> dict:
            return {"got": item is not None}

    with TestClient(Canary(API), raise_server_exceptions=False) as client:
        assert client.post("/items", json={"a": 1}).status_code == 200

        missing = client.post("/items")
        malformed = client.post("/items", content=b"{not json")
        form = client.post("/items", data={"a": "1"})
        optional = client.post("/optional")

    assert missing.status_code == 422
    assert "missing request body" in missing.json()["detail"]
    assert malformed.status_code == 422
    assert "not valid JSON" in malformed.json()["detail"]
    assert form.status_code == 422
    assert optional.status_code == 200
    assert optional.json() == {"got": False}, "可选请求体落到了缺省值上"


def test_two_body_parameters_are_refused_at_assembly():
    """#029 修好了：一个请求只有一个 body，两个形参在装配期被拒。

    没有走 FastAPI 那种"按形参名自动嵌套"——那是隐式行为；这里直接说"合并成一个模型"。
    """

    @web_cocoa
    class API:
        @post("/two")
        async def two(self, left: Item, right: Item) -> dict:
            return {"l": left.a, "r": right.a}

    app = Canary(API)
    asyncio.run(app.init())
    with pytest.raises(RouteRegistrationError, match="request-body parameters"):
        asyncio.run(app.start())


def test_a_response_that_violates_its_own_annotation_is_a_500():
    """#027 修好了：先按返回注解校验再序列化，违约是**服务端**的 bug。

    这一条在本项目里当场抓到了一个真实的不一致：分页接口声明 ``-> PageR[X]``，
    而 ``ok()`` 返回的是 ``R`` 实例——`R` 不是 `PageR[X]`。它已经这样发了几个月，
    从来没有人喊过一声。修法见 ``app/common/errors.py::ok`` 的 ``envelope`` 形参。
    """

    @web_cocoa
    class API:
        @get("/wrong")
        async def wrong(self) -> Out:
            return {"a": "not an int"}

        @get("/right")
        async def right(self) -> Out:
            return {"a": 1}

    with TestClient(Canary(API), raise_server_exceptions=False) as client:
        assert client.get("/right").json() == {"a": 1}
        wrong = client.get("/wrong")
    assert wrong.status_code == 500, "违反返回注解不再静默发出去"
    assert wrong.json() == {"detail": "Internal Server Error"}


def test_concurrent_first_requests_without_lifespan_all_succeed():
    """#026 修好了：冷启动锁。没有 lifespan 时并发首批请求只启动一次，其余在锁上等。"""

    @web_cocoa
    class API:
        starts = 0

        @on_start
        async def boot(self) -> None:
            await asyncio.sleep(0.01)  # 真实的启动都要花点时间
            type(self).starts += 1

        @get("/ping")
        async def ping(self) -> str:
            return "pong"

    async def scenario():
        app = Canary(API)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            results = await asyncio.gather(
                *[client.get("/ping") for _ in range(5)], return_exceptions=True
            )
        await app.stop()
        return results

    results = asyncio.run(scenario())
    assert [r.status_code for r in results] == [200] * 5
    assert API.starts == 1, "五个并发首请求只触发一次启动"


def test_routes_on_a_plain_cocoa_unit_are_refused_at_assembly():
    """#031 修好了：``@get`` 挂在普通 ``@cocoa`` 上不再静默失效，报 ``DeclarationError``。

    嵌套前缀删掉之后这是最容易犯的错（router 拆出去、忘了它也得是 web 单元），
    而框架的 MRO 扫描其实早就知道那些标记在哪儿。
    """

    @cocoa
    class Hidden:
        @get("/hidden")
        async def hidden(self) -> str:
            return "hidden"

    @web_cocoa(deps=[Hidden])
    class Root:
        hidden: Hidden

        @get("/shown")
        async def shown(self) -> str:
            return "shown"

    with pytest.raises(DeclarationError, match="Hidden"):
        asyncio.run(Canary(Root).init())


def test_a_prefix_without_a_leading_slash_is_normalised():
    """#033 修好了：``prefix="api"`` 与 ``@get("x")`` 现在遵守同一条规则。"""

    @web_cocoa(prefix="api")
    class NoSlash:
        @get("x")
        async def x(self) -> str:
            return "x"

    with TestClient(Canary(NoSlash)) as client:
        assert client.get("/api/x").json() == "x"
        assert sorted(client.get("/openapi.json").json()["paths"]) == ["/api/x"]


# --- 最终版新增的能力 ------------------------------------------------------


def test_status_code_and_doc_metadata_on_the_route_declaration():
    """``status_code`` 是唯一一处能力缺口：从前要 201 只能自己造 ``Response``，

    那样就同时丢了返回值校验和文档里的响应 schema。``tags`` / ``summary`` /
    ``deprecated`` 是纯文档元数据，``description`` 直接取 docstring。
    """

    @web_cocoa(prefix="/api", tags=["catalog"])
    class API:
        @post("/books", status_code=201, summary="上架一本书")
        async def create(self, item: Item) -> Out:
            """创建一条书目记录。"""
            return Out(a=item.a)

        @delete("/books/{book_id}", status_code=204)
        async def remove(self, book_id: int) -> None:
            return None

        @get("/legacy", deprecated=True, tags=["legacy"])
        async def legacy(self) -> str:
            return "old"

    with TestClient(Canary(API)) as client:
        created = client.post("/api/books", json={"a": 7})
        removed = client.delete("/api/books/1")
        doc = client.get("/openapi.json").json()

    assert created.status_code == 201
    assert created.json() == {"a": 7}, "状态码变了，返回值照常按注解校验并序列化"
    assert removed.status_code == 204
    assert removed.content == b"", "204 按 HTTP 规范不带响应体，不是 JSON 的 null"

    create_op = doc["paths"]["/api/books"]["post"]
    assert set(create_op["responses"]) == {"201"}
    assert create_op["summary"] == "上架一本书"
    assert create_op["description"] == "创建一条书目记录。"
    assert create_op["tags"] == ["catalog"]
    assert doc["paths"]["/api/legacy"]["get"]["tags"] == ["catalog", "legacy"]
    assert doc["paths"]["/api/legacy"]["get"]["deprecated"] is True


def test_constraints_written_in_annotated_are_kept():
    """``Annotated[int, Field(gt=0)]`` 的约束从前被无声丢掉——既不校验也不进文档。"""

    @web_cocoa
    class API:
        @get("/page")
        async def page(self, page: Annotated[int, Field(gt=0)] = 1) -> int:
            return page

    with TestClient(Canary(API)) as client:
        assert client.get("/page?page=3").json() == 3
        assert client.get("/page?page=-5").status_code == 422
        schema = client.get("/openapi.json").json()["paths"]["/page"]["get"]["parameters"][0]
    assert schema["schema"]["exclusiveMinimum"] == 0


# --- STILL BROKEN: async def 只挡住了最好认的那一种阻塞 ----------------------


def test_an_async_handler_with_a_sync_body_stalls_the_loop_just_as_badly():
    """把 ``def`` 改成 ``async def`` 而函数体不动，阻塞一点没少。

    ``require_async`` 只看 handler 的签名，不看它调用了什么，也不管
    ``@on_start`` / 仓储方法。HEAD 新增的 ``CANARY_SLOW_CALLBACK_SECONDS``
    补上了运行期那一半——但它默认关闭，且看不见启动期（见场景二的边界测试）。
    见 doc/bug/020-the-async-rule-only-covers-the-handler-signature.md
    """

    @cocoa
    class SyncRepo:
        def query(self) -> str:
            time.sleep(0.1)
            return "row"

    @web_cocoa(deps=[SyncRepo])
    class Naive:
        sync_repo: SyncRepo

        @get("/slow")
        async def slow(self) -> str:
            return self.sync_repo.query()

        @get("/health")
        async def health(self) -> str:
            return "ok"

    async def scenario() -> float:
        app = Canary(Naive)
        await app.init()
        await app.start()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            await client.get("/health")  # 预热
            started = time.perf_counter()

            async def health_latency() -> float:
                await asyncio.sleep(0.01)
                await client.get("/health")
                return time.perf_counter() - started

            results = await asyncio.gather(
                *[client.get("/slow") for _ in range(10)], health_latency()
            )
        await app.stop()
        return results[-1]

    health = asyncio.run(scenario())
    assert health > 0.5, (
        "无关端点的端到端延迟没有被 10 个阻塞调用拖垮——"
        "框架已经能看穿 handler 函数体，可以放宽本项目的全异步约束"
    )

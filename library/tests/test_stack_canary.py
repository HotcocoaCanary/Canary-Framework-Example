"""只属于应用单元那一层的东西。

``canary_framework.web.asgi.app`` 的规则和 FastAPI 不完全一样，这个文件把**差别**钉住：
尾斜杠严格、405 带 ``Allow``、``HEAD`` 由 ``GET`` 应答、``@error`` 处理器、``Response``
与 ``HTTPError`` 的用法，以及它**没有**的那些东西。

换一层 HTTP 时真正会咬人的就是这些，所以每条都写明"FastAPI 那边是什么样"。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from canary_framework import LifecycleError, dep
from canary_framework.test import running, unit
from canary_framework.web.asgi.app import HTTPError, Request, Response, Router, get, post

from app.api.canary import LibraryApi
from app.common.errors import DomainError
from app.infra.db import Database


def _client(app) -> httpx.AsyncClient:
    """``app`` 是应用单元自己——它就是一个 ASGI 应用。"""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- 没有的东西 -------------------------------------------------------------


async def test_there_is_no_openapi_and_no_docs(canary_client) -> None:
    """这一层不生成 OpenAPI，所以 ``/docs`` 与 ``/openapi.json`` 只是两个没人应答的路径。"""
    for path in ("/docs", "/openapi.json", "/redoc"):
        answer = await canary_client.get(path)
        assert (answer.status_code, answer.json()) == (404, {"detail": "Not Found"}), path


async def test_the_route_table_has_no_public_reader(canary_client) -> None:
    """**【毛病】** 没有任何公开办法问"你注册了哪些路径"。

    FastAPI 那边读 ``/openapi.json`` 就有；这一层既没有 OpenAPI，也没有导出路由表的东西，
    只能去动 ``canary_framework.web.asgi.app.router.collect``——它不在 ``__init__`` 的
    ``__all__`` 里。运维要确认"这个版本到底挂了哪些接口"时，这是个真缺口。
    """
    from canary_framework.web.asgi.app import __all__ as exported

    assert "collect" not in exported
    assert "Table" not in exported


async def test_the_application_answers_the_lifespan_protocol() -> None:
    """这一层的应用自己应答 lifespan，所以能交给任何驱动 lifespan 的服务器或测试客户端。

    它**不**把 lifespan 转发到别处：单元的启动与回收归 Canary 的生命周期管
    （``running(...)`` 或 ``async with``），不该由 ASGI 再来一遍。``asgi.dispatch`` 也是
    这样处理的（见 relay 场景）。
    """
    sent: list[dict] = []
    incoming = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive() -> dict:
        return next(incoming)

    async def send(message: dict) -> None:
        sent.append(message)

    async with running(LibraryApi) as api:
        # 打在**单元自己**身上：应用单元就是那个 ASGI 应用（``api.app`` 是它内部处理请求的
        # 那一层，不管 lifespan）。已经由 Canary 启动过，所以这里只是应答。
        await asyncio.wait_for(api({"type": "lifespan"}, receive, send), timeout=2)
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]


# --- 路径匹配的规则 ---------------------------------------------------------


async def test_a_trailing_slash_is_a_different_path(canary_client) -> None:
    """尾斜杠严格区分，不做重定向——FastAPI 那边会 307 跳到带斜杠的那个。

    本项目的 ``/api/readers/`` 写的是 ``@post("/")``，所以**带**斜杠才是它。少写一个斜杠
    在这一层是 404，在 FastAPI 那层是 307 + Location。两层都不会把请求办成，但报的不一样，
    客户端要注意。
    """
    assert (await canary_client.get("/api/readers/")).status_code == 200
    assert (await canary_client.get("/api/readers")).status_code == 404


async def test_a_method_nobody_answers_is_405_and_says_which_are(canary_client) -> None:
    response = await canary_client.put("/api/catalog/books")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, POST"


async def test_head_is_answered_by_get(canary_client) -> None:
    assert (await canary_client.head("/api/health")).status_code == 200


async def test_a_static_segment_wins_over_a_parameter(canary_client) -> None:
    """``/api/catalog/categories`` 与 ``/api/catalog/books/{book_id}`` 同时存在也不会打架。"""
    assert (await canary_client.get("/api/catalog/categories")).status_code == 200
    assert (await canary_client.get("/api/catalog/books/bk_nope")).status_code == 404


# --- 异常：@error 标记的处理器 ----------------------------------------------


async def test_domain_errors_land_in_the_envelope(canary_client) -> None:
    """``@error(DomainError)`` 一处，全部路由生效——和 FastAPI 的异常处理器等价。"""
    answer = await canary_client.get("/api/catalog/books/bk_does_not_exist")
    assert answer.status_code == 404
    body = answer.json()
    assert (body["code"], body["data"]) == (404, None)


class ProbeApi(Router, prefix="/probe"):
    """A router unit used only by these tests."""

    @get("/boom")
    async def boom(self) -> dict:
        raise HTTPError(418, {"why": "short and stout"}, headers={"x-kind": "tea"})

    @get("/bug")
    async def bug(self) -> dict:
        raise ZeroDivisionError("这是真 bug")

    @get("/domain")
    async def domain(self) -> dict:
        raise DomainError("这是业务失败", 400)

    @post("/made", status=201)
    async def made(self, body: dict) -> dict:
        return {"got": body}

    @post("/gone")
    async def gone(self) -> None:
        return None

    @get("/raw")
    async def raw(self, request: Request) -> Response:
        return Response("pong", headers={"x-probe": "yes"})

    @get("/tags")
    async def tags(self, tag: list[int] = [], keyword: str | None = None) -> dict:  # noqa: B006
        return {"tag": tag, "keyword": keyword}


class Probed(LibraryApi):
    """继承应用单元：路由、``@error`` 处理器都带过来，再多挂一个路由单元。"""

    probe = dep(ProbeApi)


async def test_http_error_answers_itself() -> None:
    """``HTTPError`` 在任何地方抛都行，响应体是 ``{"detail": ...}``，还能带响应头。"""
    async with running(Probed) as api, _client(api) as http:
        answer = await http.get("/probe/boom")
        assert answer.status_code == 418
        assert answer.json() == {"detail": {"why": "short and stout"}}
        assert answer.headers["x-kind"] == "tea"


async def test_a_real_bug_is_500_and_says_nothing_about_itself() -> None:
    """没有处理器的异常是 500，响应里不带内部细节——栈只进日志。"""
    async with running(Probed) as api, _client(api) as http:
        answer = await http.get("/probe/bug")
        assert answer.status_code == 500
        assert answer.json() == {"detail": "Internal Server Error"}
        assert "ZeroDivision" not in answer.text


async def test_a_domain_error_from_a_subclassed_app_still_lands() -> None:
    """``@error`` 是按属性名解析的标记，所以子类照常继承它。"""
    async with running(Probed) as api, _client(api) as http:
        answer = await http.get("/probe/domain")
        assert (answer.status_code, answer.json()["code"]) == (400, 400)


# --- 返回值与形参 -----------------------------------------------------------


async def test_the_status_comes_from_the_mark_and_none_is_empty() -> None:
    async with running(Probed) as api, _client(api) as http:
        made = await http.post("/probe/made", json={"a": 1})
        assert (made.status_code, made.json()) == (201, {"got": {"a": 1}})
        gone = await http.post("/probe/gone")
        assert (gone.status_code, gone.content) == (204, b"")


async def test_a_response_is_sent_as_it_is() -> None:
    async with running(Probed) as api, _client(api) as http:
        answer = await http.get("/probe/raw")
        assert (answer.text, answer.headers["x-probe"]) == ("pong", "yes")
        assert answer.headers["content-type"] == "text/plain; charset=utf-8"


async def test_repeated_query_parameters_become_a_list() -> None:
    """``list[...]`` 的形参取全部同名值——FastAPI 要写 ``Query()`` 才有这个。"""
    async with running(Probed) as api, _client(api) as http:
        answer = await http.get("/probe/tags?tag=1&tag=2&keyword=k")
        assert answer.json() == {"tag": [1, 2], "keyword": "k"}


async def test_every_failed_parameter_is_reported_at_once(canary_client) -> None:
    """422 的格式按 FastAPI 的形状来：``{"detail": [{"loc": ..., "msg": ..., "type": ...}]}``。"""
    answer = await canary_client.post("/api/catalog/books", json={"title": "缺作者"})
    assert answer.status_code == 422
    first = answer.json()["detail"][0]
    assert first["loc"][0] == "body"
    assert set(first) == {"loc", "msg", "type"}


# --- 文档里写明的那个坑 -----------------------------------------------------


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_a_method_called_get_shadows_the_decorator() -> None:
    """类体里的 ``def get`` 会遮住它**后面**的 ``@get``——两个包都有这个坑。

    症状是类定义时的 ``TypeError``（装饰器变成了那个协程方法），不是运行时的 404，
    所以至少不会悄悄漏掉接口。
    """
    with pytest.raises(TypeError):

        class Shadowed(Router, prefix="/x"):
            @get("/a")
            async def get(self) -> dict:
                return {}

            @get("/b")
            async def other(self) -> dict:
                return {}


# --- 路由树就是依赖图（只有这一层有"路由单元"）-------------------------------


def test_the_route_tree_is_the_dependency_graph() -> None:
    """应用依赖 ``Api``，``Api`` 依赖各模块的路由单元，路由单元依赖自己的 service。

    原生 FastAPI 那一层没有这回事：路由是模块级的 ``APIRouter``，依赖图上只有 service。
    """
    from canary_framework import deps_of

    from app.api.canary import Api, LibraryApi, SystemApi
    from app.api.canary.catalog import CatalogApi
    from app.api.canary.chat import AssistantApi
    from app.api.canary.loan import CirculationApi
    from app.api.canary.rag import RagApi
    from app.api.canary.reader import ReaderApi
    from app.module.catalog.service import CatalogService

    assert set(deps_of(LibraryApi)) == {Api}
    assert set(deps_of(Api)) == {
        SystemApi,
        CatalogApi,
        ReaderApi,
        CirculationApi,
        RagApi,
        AssistantApi,
    }
    assert set(deps_of(CatalogApi)) == {CatalogService}


async def test_an_endpoint_is_a_plain_bound_method() -> None:
    """接口方法是绑定方法，不经 HTTP 也能调——这一层最便宜的那种测试。"""
    from canary_framework.test import running

    from app.api.canary import LibraryApi as Api
    from app.module.catalog.schema import CreateBookRequest

    async with running(Api) as api:
        answer = await api.api.system.health()
        assert answer.data["status"] == "ok"

        book = await api.api.catalog.create_book(
            CreateBookRequest(title="不经 HTTP", author="x")
        )
        fetched = await api.api.catalog.get_book(book.data.id)
        assert fetched.data.title == "不经 HTTP"


# --- 应用单元自己就是 ASGI 应用：交给原生服务器 ------------------------------


async def drive_lifespan(app) -> tuple[list[dict], callable]:
    """Start *app* the way an ASGI server does, and return ``(sent, shutdown)``.

    像 uvicorn 那样用 lifespan 消息启动一个应用单元：发 ``lifespan.startup``，等
    ``startup.complete``；``shutdown()`` 发停止消息并等回收完成。这就是
    ``uvicorn asgi:app`` 背后的全部协议。
    """
    inbox: asyncio.Queue[dict] = asyncio.Queue()
    sent: list[dict] = []

    async def receive() -> dict:
        return await inbox.get()

    async def send(message: dict) -> None:
        sent.append(message)

    running_lifespan = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    await inbox.put({"type": "lifespan.startup"})
    for _ in range(500):
        if sent:
            break
        await asyncio.sleep(0.005)
    assert sent and sent[0]["type"] == "lifespan.startup.complete", sent

    async def shutdown() -> None:
        await inbox.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(running_lifespan, timeout=10)

    return sent, shutdown


async def test_an_asgi_server_can_start_and_stop_the_graph_itself() -> None:
    """``uvicorn asgi:app``：没有我们的服务器单元，图由 lifespan 消息驱动。

    这是三种组合里的第二种（见 ``app/api/__init__.py``）：我们的应用单元 + 原生 ASGI
    服务器。启动时这个单元连同它的依赖按序 ``init`` / ``start``（数据库就位），停止时逆序
    回收——``asgi.py`` 里那一行 ``app = LibraryApi()`` 就够了。
    """
    from canary_framework import scope_of
    from canary_framework import start as start_phase

    api = LibraryApi()
    sent, shutdown = await drive_lifespan(api)

    assert unit(api, Database).engine is not None, "lifespan 把整张图启动了"
    async with _client(api) as http:
        answer = await http.post("/api/catalog/books", json={"title": "uvicorn", "author": "x"})
        assert answer.status_code == 200

    await shutdown()
    assert sent[-1] == {"type": "lifespan.shutdown.complete"}
    assert not scope_of(api).entered(start_phase), "停止消息把整张图回收了"


async def test_serving_before_the_lifecycle_says_so() -> None:
    """没启动就收到请求：说清楚该怎么启动，而不是 ``AttributeError``。"""
    api = LibraryApi()
    transport = httpx.ASGITransport(app=api, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        with pytest.raises(LifecycleError, match="before its lifecycle began"):
            await http.get("/api/health")


async def test_a_graph_started_by_canary_is_not_started_twice() -> None:
    """已经由 Canary 启动的应用，收到 lifespan 消息只应答，不重复驱动。

    所以"我们的 Server + 应用单元"与"原生服务器 + 应用单元"两种组合不会互相打架——
    前者本来就不发 lifespan 消息，而即使有人发了，应用也只是回个确认。
    """
    from canary_framework import scope_of
    from canary_framework import start as start_phase

    async with running(LibraryApi) as api:
        _sent, shutdown = await drive_lifespan(api)
        await shutdown()
        # 图还在跑：lifespan 的停止消息没有把它拆掉
        assert scope_of(api).entered(start_phase)
        assert (await (await _open(api)).get("/api/health")).status_code == 200


async def _open(api):
    """A client that the caller does not have to close (test-scoped)."""
    transport = httpx.ASGITransport(app=api)
    return httpx.AsyncClient(transport=transport, base_url="http://test")

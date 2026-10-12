"""只属于 web 那一层的东西。

``canary_framework.asgi.web`` 的规则和 FastAPI 不完全一样，这个文件把**差别**钉住：
尾斜杠严格、405 带 ``Allow``、``HEAD`` 由 ``GET`` 应答、``@error`` 处理器、``Response``
与 ``HTTPError`` 的用法，以及它**没有**的那些东西。

换一层 HTTP 时真正会咬人的就是这些，所以每条都写明"FastAPI 那边是什么样"。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework import dep
from canary_framework.asgi.web import HTTPError, Request, Response, Router, get, post
from canary_framework.test import running

from app.api.web import LibraryApi
from app.common.errors import DomainError


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- 没有的东西 -------------------------------------------------------------


async def test_there_is_no_openapi_and_no_docs(web_client) -> None:
    """这一层不生成 OpenAPI，所以 ``/docs`` 与 ``/openapi.json`` 只是两个没人应答的路径。"""
    for path in ("/docs", "/openapi.json", "/redoc"):
        answer = await web_client.get(path)
        assert (answer.status_code, answer.json()) == (404, {"detail": "Not Found"}), path


async def test_the_route_table_has_no_public_reader(web_client) -> None:
    """**【毛病】** 没有任何公开办法问"你注册了哪些路径"。

    FastAPI 那边读 ``/openapi.json`` 就有；这一层既没有 OpenAPI，也没有导出路由表的东西，
    只能去动 ``canary_framework.asgi.web.router.collect``——它不在 ``__init__`` 的
    ``__all__`` 里。运维要确认"这个版本到底挂了哪些接口"时，这是个真缺口。
    """
    from canary_framework.asgi.web import __all__ as exported

    assert "collect" not in exported
    assert "Table" not in exported


# --- 路径匹配的规则 ---------------------------------------------------------


async def test_a_trailing_slash_is_a_different_path(web_client) -> None:
    """尾斜杠严格区分，不做重定向——FastAPI 那边会 307 跳到带斜杠的那个。

    本项目的 ``/api/readers/`` 写的是 ``@post("/")``，所以**带**斜杠才是它。少写一个斜杠
    在这一层是 404，在 FastAPI 那层是 307 + Location。两层都不会把请求办成，但报的不一样，
    客户端要注意。
    """
    assert (await web_client.get("/api/readers/")).status_code == 200
    assert (await web_client.get("/api/readers")).status_code == 404


async def test_a_method_nobody_answers_is_405_and_says_which_are(web_client) -> None:
    response = await web_client.put("/api/catalog/books")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, POST"


async def test_head_is_answered_by_get(web_client) -> None:
    assert (await web_client.head("/api/health")).status_code == 200


async def test_a_static_segment_wins_over_a_parameter(web_client) -> None:
    """``/api/catalog/categories`` 与 ``/api/catalog/books/{book_id}`` 同时存在也不会打架。"""
    assert (await web_client.get("/api/catalog/categories")).status_code == 200
    assert (await web_client.get("/api/catalog/books/bk_nope")).status_code == 404


# --- 异常：@error 标记的处理器 ----------------------------------------------


async def test_domain_errors_land_in_the_envelope(web_client) -> None:
    """``@error(DomainError)`` 一处，全部路由生效——和 FastAPI 的异常处理器等价。"""
    answer = await web_client.get("/api/catalog/books/bk_does_not_exist")
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
    async with running(Probed) as api, _client(api.app) as http:
        answer = await http.get("/probe/boom")
        assert answer.status_code == 418
        assert answer.json() == {"detail": {"why": "short and stout"}}
        assert answer.headers["x-kind"] == "tea"


async def test_a_real_bug_is_500_and_says_nothing_about_itself() -> None:
    """没有处理器的异常是 500，响应里不带内部细节——栈只进日志。"""
    async with running(Probed) as api, _client(api.app) as http:
        answer = await http.get("/probe/bug")
        assert answer.status_code == 500
        assert answer.json() == {"detail": "Internal Server Error"}
        assert "ZeroDivision" not in answer.text


async def test_a_domain_error_from_a_subclassed_app_still_lands() -> None:
    """``@error`` 是按属性名解析的标记，所以子类照常继承它。"""
    async with running(Probed) as api, _client(api.app) as http:
        answer = await http.get("/probe/domain")
        assert (answer.status_code, answer.json()["code"]) == (400, 400)


# --- 返回值与形参 -----------------------------------------------------------


async def test_the_status_comes_from_the_mark_and_none_is_empty() -> None:
    async with running(Probed) as api, _client(api.app) as http:
        made = await http.post("/probe/made", json={"a": 1})
        assert (made.status_code, made.json()) == (201, {"got": {"a": 1}})
        gone = await http.post("/probe/gone")
        assert (gone.status_code, gone.content) == (204, b"")


async def test_a_response_is_sent_as_it_is() -> None:
    async with running(Probed) as api, _client(api.app) as http:
        answer = await http.get("/probe/raw")
        assert (answer.text, answer.headers["x-probe"]) == ("pong", "yes")
        assert answer.headers["content-type"] == "text/plain; charset=utf-8"


async def test_repeated_query_parameters_become_a_list() -> None:
    """``list[...]`` 的形参取全部同名值——FastAPI 要写 ``Query()`` 才有这个。"""
    async with running(Probed) as api, _client(api.app) as http:
        answer = await http.get("/probe/tags?tag=1&tag=2&keyword=k")
        assert answer.json() == {"tag": [1, 2], "keyword": "k"}


async def test_every_failed_parameter_is_reported_at_once(web_client) -> None:
    """422 的格式按 FastAPI 的形状来：``{"detail": [{"loc": ..., "msg": ..., "type": ...}]}``。"""
    answer = await web_client.post("/api/catalog/books", json={"title": "缺作者"})
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

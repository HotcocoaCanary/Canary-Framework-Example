"""只属于 web 那一层的规则：没有 OpenAPI、尾斜杠严格、405 带 ``Allow``、``@error`` 处理器。

换一层 HTTP 时真正会咬人的就是这些，所以每条都写明"FastAPI 那边是什么样"。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework import dep
from canary_framework.asgi.web import HTTPError, Request, Response, Router, error, get
from canary_framework.test import running

from relay.clock import Clock
from relay.http import web as layer
from relay.settings import AdminSettings, EdgeSettings
from relay.testing import ManualClock

TOKEN = "test-token"


@pytest.fixture
async def relay_web():
    doubles = {
        EdgeSettings: EdgeSettings(host="127.0.0.1", port=0, site_id="test-site", sweep_interval_seconds=3600.0),
        AdminSettings: AdminSettings(host="127.0.0.1", port=0, token=TOKEN),
        Clock: ManualClock(),
    }
    async with running(layer.Relay, doubles) as root:
        yield root


@pytest.fixture
async def public(relay_web):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{relay_web.public.port}") as client:
        yield client


async def test_there_is_no_openapi(public) -> None:
    """这一层不生成 OpenAPI，所以 ``/docs`` 与 ``/openapi.json`` 只是没人应答的路径。"""
    for path in ("/docs", "/openapi.json"):
        answer = await public.get(path)
        assert (answer.status_code, answer.json()) == (404, {"detail": "Not Found"}), path


async def test_a_trailing_slash_is_a_different_path(public) -> None:
    """尾斜杠严格区分，不做重定向——FastAPI 那边是 307 + Location。"""
    assert (await public.get("/devices")).status_code == 200
    assert (await public.get("/devices/")).status_code == 404


async def test_a_method_nobody_answers_is_405_and_says_which_are(public) -> None:
    answer = await public.put("/devices")
    assert answer.status_code == 405
    assert answer.headers["allow"] == "GET"


async def test_head_is_answered_by_get(public) -> None:
    assert (await public.head("/health")).status_code == 200


async def test_the_dispatcher_and_the_app_both_answer_404_the_same_way(public) -> None:
    """``/metricsx`` 落到 ``/``（这一层的应用）上，``/zzz`` 也一样——两者都是 404。

    注意报文不同：应用答的是 ``{"detail": "Not Found"}``，而 ``asgi.dispatch`` 自己拒绝
    时答的是纯文本 ``Not Found``（没有任何前缀匹配时）。本场景的 ``/`` 永远匹配，所以这里
    看到的都是应用那一个。
    """
    answer = await public.get("/metricsx")
    assert (answer.status_code, answer.json()) == (404, {"detail": "Not Found"})


# -- @error 处理器 ---------------------------------------------------------


class ProbeApi(Router, prefix="/probe"):
    @get("/boom")
    async def boom(self) -> dict:
        raise HTTPError(418, {"why": "short and stout"})

    @get("/bug")
    async def bug(self) -> dict:
        raise ZeroDivisionError("真 bug")


class ProbedApp(layer.PublicApi):
    """继承应用单元：路由与 ``@error`` 处理器都带过来，再多挂一个路由单元。"""

    probe = dep(ProbeApi)

    @error(ZeroDivisionError)
    async def on_bug(self, _: Request, exc: ZeroDivisionError) -> Response:
        """子类加一个处理器：按异常类型最贴近的那个来。"""
        return Response.json({"detail": "我们记下了", "kind": type(exc).__name__}, status=500)


async def test_an_error_handler_added_by_a_subclass_wins() -> None:
    doubles = {EdgeSettings: EdgeSettings(site_id="bare"), Clock: ManualClock()}
    async with running(ProbedApp, doubles) as api:
        transport = httpx.ASGITransport(app=api.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            teapot = await http.get("/probe/boom")
            assert (teapot.status_code, teapot.json()) == (418, {"detail": {"why": "short and stout"}})

            bug = await http.get("/probe/bug")
            assert bug.status_code == 500
            assert bug.json() == {"detail": "我们记下了", "kind": "ZeroDivisionError"}

            # 继承来的那个处理器照常生效
            missing = await http.get("/devices/ghost")
            assert (missing.status_code, missing.json()["device_id"]) == (404, "ghost")

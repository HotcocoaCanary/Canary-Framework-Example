"""只属于应用单元那一层的规则：没有 OpenAPI、尾斜杠严格、405 带 ``Allow``、``@error`` 处理器。

换一层 HTTP 时真正会咬人的就是这些，所以每条都写明"FastAPI 那边是什么样"。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework import dep
from canary_framework.test import running
from canary_framework.web.asgi.app import HTTPError, Request, Response, Router, error, get

from relay.clock import Clock
from relay.http import canary as layer
from relay.settings import AdminSettings, EdgeSettings
from relay.testing import ManualClock

TOKEN = "test-token"


@pytest.fixture
async def relay_canary():
    doubles = {
        EdgeSettings: EdgeSettings(host="127.0.0.1", port=0, site_id="test-site", sweep_interval_seconds=3600.0),
        AdminSettings: AdminSettings(host="127.0.0.1", port=0, token=TOKEN),
        Clock: ManualClock(),
    }
    async with running(layer.Relay, doubles) as root:
        yield root


@pytest.fixture
async def public(relay_canary):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{relay_canary.public.port}") as client:
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
        transport = httpx.ASGITransport(app=api, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            teapot = await http.get("/probe/boom")
            assert (teapot.status_code, teapot.json()) == (418, {"detail": {"why": "short and stout"}})

            bug = await http.get("/probe/bug")
            assert bug.status_code == 500
            assert bug.json() == {"detail": "我们记下了", "kind": "ZeroDivisionError"}

            # 继承来的那个处理器照常生效
            missing = await http.get("/devices/ghost")
            assert (missing.status_code, missing.json()["device_id"]) == (404, "ghost")


# --- 只有这一层有"路由单元" -------------------------------------------------


async def test_one_router_unit_under_two_prefixes(relay_canary) -> None:
    """``HealthApi`` 被两处依赖：``/health`` 与 ``/admin/health``，背后**一个实例**。

    原生 FastAPI 那一层也能共享，但共享的是**函数**：同一个 ``site_health`` 被两个
    ``APIRouter`` 挂两次（见 ``relay/http/fastapi.py``）。差别在"共享实例"与"共享函数"。
    """
    from canary_framework.test import unit

    shared = unit(relay_canary, layer.HealthApi)
    assert shared.served == 0

    public_url = f"http://127.0.0.1:{relay_canary.public.port}"
    admin_url = f"http://127.0.0.1:{relay_canary.admin.port}"
    async with (
        httpx.AsyncClient(base_url=public_url) as public_client,
        httpx.AsyncClient(base_url=admin_url, headers={"x-admin-token": TOKEN}) as admin_client,
    ):
        assert (await public_client.get("/health")).status_code == 200
        assert (await admin_client.get("/admin/health")).status_code == 200
    assert shared.served == 2  # 一个实例数了两次


async def test_endpoint_methods_are_plain_bound_methods(clock) -> None:
    """接口方法可以不经 HTTP 直接 await —— ``get`` / ``post`` 只打标记，不改造方法。

    原生 FastAPI 那一层的接口是模块级函数，要调它得自己把 ``Depends`` 的那些参数凑出来，
    所以没有这种"最便宜的一层测试"。
    """
    from canary_framework.test import running

    from relay.schema import Heartbeat

    doubles = {EdgeSettings: EdgeSettings(site_id="bare"), Clock: clock}
    async with running(layer.PublicApi, doubles) as api:
        view = await api.devices.heartbeat("pos-1", Heartbeat(kind="pos", metrics={"paper": 0.5}))
        assert (view.device_id, view.status, view.heartbeats) == ("pos-1", "online", 1)

        health = await api.health.health()
        assert health["site"] == "bare"
        assert api.devices.fleet is api.health.fleet  # 共享的两个单元就是同一个实例

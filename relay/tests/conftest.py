"""Fixtures —— 一个进程两个端口，两层 HTTP 各跑一遍。

``stack`` 被参数化成 ``fastapi`` 与 ``web``，而 ``relay`` / ``public`` / ``admin`` /
``api_client`` 都依赖它，所以**每个用到它们的测试都会跑两遍**。两层只是 HTTP，业务是
同一份（台账、计数、巡检、``/metrics``、``/ws/events`` 都共用），所以它们的答案必须一样。

只属于某一层的东西在 ``test_stack_fastapi.py`` 与 ``test_stack_web.py``。

两种测法都在这里给出，因为它们能发现的东西不同：

* ``relay`` / ``public`` / ``admin``：``port = 0`` 的**真实套接字**。两个端口、三个应用、
  路径分发、WebSocket 握手、优雅停机——这些只有真的监听了才测得到。
* ``api_client``：只启动 ``PublicApi`` 这一个应用单元，用 ``httpx.ASGITransport`` 直接打
  它的 ``self.app``。没有服务器，没有端口，没有分发，快且与网络无关。

端口是用**替身换配置**换成 0 的：``running(Relay, {EdgeSettings: EdgeSettings(port=0)})``。
被替换的单元不会被构造，替身按自身类型参与生命周期。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from canary_framework.test import running

from relay.clock import Clock
from relay.http import NAMES
from relay.http import root as root_class
from relay.http import stack as stack_module
from relay.settings import AdminSettings, EdgeSettings
from relay.testing import ManualClock

#: 口令写死，省得测试去读 SecretStore。
TOKEN = "test-token"


@pytest.fixture(params=NAMES)
def stack(request) -> str:
    """``fastapi`` 与 ``web`` 各一遍。"""
    return request.param


@pytest.fixture
def layer(stack):
    """The module implementing the current stack —— 它给出这一层的路由单元与应用单元。

    两层的类是**不同的类**（``relay.http.fastapi.HealthApi`` 与
    ``relay.http.web.HealthApi``），所以要断言类的测试从这里取。
    """
    return stack_module(stack)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def doubles(clock: ManualClock) -> dict:
    """What every test replaces: both ports to 0, the clock, and no sweep loop.

    ``sweep_interval_seconds`` 调得很大，是为了后台循环不要在测试中间自己跑——要巡检时
    测试自己调 ``sweep_once()``。
    """
    return {
        EdgeSettings: EdgeSettings(
            host="127.0.0.1",
            port=0,
            site_id="test-site",
            heartbeat_timeout_seconds=90.0,
            sweep_interval_seconds=3600.0,
            stream_queue_size=8,
        ),
        AdminSettings: AdminSettings(host="127.0.0.1", port=0, token=TOKEN),
        Clock: clock,
    }


@pytest.fixture
async def relay(stack: str, doubles: dict):
    """The whole process: two listening ports, four applications, one sweep loop."""
    async with running(root_class(stack), doubles) as root:
        yield root


@pytest.fixture
async def public(relay) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the store-facing port —— 真的走 TCP。"""
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{relay.public.port}") as client:
        yield client


@pytest.fixture
async def admin(relay) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the internal port, with the token attached."""
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{relay.admin.port}", headers={"x-admin-token": TOKEN}
    ) as client:
        yield client


@pytest.fixture
async def api_client(stack: str, clock: ManualClock) -> AsyncIterator[httpx.AsyncClient]:
    """The public application alone, with no server and no socket.

    只启动应用单元那一棵子树：``PublicApi`` 是图上的一个普通单元，可以不要 ``Server`` 就
    启动——这正是"应用是值，端口才需要唯一"的另一面。
    """
    doubles = {EdgeSettings: EdgeSettings(site_id="test-site"), Clock: clock}
    async with running(stack_module(stack).PublicApi, doubles) as api:
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
            yield client

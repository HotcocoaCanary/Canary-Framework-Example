"""Fixtures —— 迁移的两个阶段，各跑一遍。

``stage`` 被参数化成 ``"1"``（只换服务器）与 ``"2"``（新模块与老应用并存），而
``server`` / ``client`` 都依赖它，所以**老接口的那些测试会在两个阶段各跑一遍**——迁移的
第一条要求就是"老的一行不改、也不许变样"。

走的是**真实套接字**（``port = 0``）：这个场景要压的正是"我们的服务器单元服务别人家的
应用"，不真的监听就没意思了。只测 ``/v2`` 那个应用单元本身时用 ``ASGITransport``，见
``v2_client``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from canary_framework.test import running
from canary_framework.web.asgi.server import Server

from shop import legacy
from shop.graph import ShopGraph, V2Api
from shop.server import STAGES


@pytest.fixture(autouse=True)
def clean_legacy_state() -> None:
    """The old code keeps its orders in a module-level dict —— 测试之间要洗掉。

    这正是老代码的样子，也正是迁移要解决的事：图上的单元每次 ``running`` 都是新的，
    模块级的状态不是。
    """
    legacy._ORDERS.clear()


@pytest.fixture(params=sorted(STAGES))
def stage(request) -> str:
    """``"1"`` 与 ``"2"`` 各一遍。"""
    return request.param


def listener(stage: str) -> type[Server]:
    """The stage's server unit, with the port left to the system."""
    base = STAGES[stage]
    return type(f"Test{base.__name__}", (base,), {"host": "127.0.0.1", "port": 0})


@pytest.fixture
async def server(stage: str):
    """The stage, listening on a port the system picked."""
    async with running(listener(stage)) as unit:
        yield unit


@pytest.fixture
async def client(server) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}") as http:
        yield http


@pytest.fixture
async def graph() -> AsyncIterator[ShopGraph]:
    """The business half alone —— 不要 HTTP，也不要服务器。"""
    async with running(ShopGraph) as root:
        yield root


@pytest.fixture
async def v2_client() -> AsyncIterator[httpx.AsyncClient]:
    """The migrated modules alone: the application unit **is** the ASGI application."""
    async with running(V2Api) as api:
        transport = httpx.ASGITransport(app=api, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http

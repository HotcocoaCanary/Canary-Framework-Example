"""Fixtures —— 同一套行为测试，对两层 HTTP 各跑一遍。

``stack`` 这个 fixture 被参数化成 ``canary``（路由与应用都是单元）与 ``fastapi``（一个原生
FastAPI 应用 + 一座按类型取单元的桥），而 ``root`` / ``app`` / ``client`` / ``database``
都依赖它，所以**每个用到 client 的测试都会跑两遍**。两层只是 HTTP，业务是同一份，所以
它们的答案必须一样——不一样的地方就是这一轮要找的东西。

只属于某一层的东西（OpenAPI 与 ``/docs``、路由单元的 405/HEAD 细节）在
``tests/test_stack_fastapi.py`` 与 ``tests/test_stack_canary.py`` 里。

``AppConfig`` 默认 ``storage=sqlite`` + ``sqlite_path=":memory:"``，``Database`` 又把内存
库钉在单条连接上，所以每个测试拿到一份私有 schema，随应用一起消失。请求不经网络也不要
服务器：``httpx.ASGITransport`` 直接打那个 ASGI 应用。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from canary_framework.test import unit

from app.api import NAMES
from app.infra.db import Database
from app.testing import running_stack


def connect(app) -> httpx.AsyncClient:
    """An HTTP client talking straight to an ASGI application, no socket in between."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(params=NAMES)
def stack(request) -> str:
    """``canary`` 与 ``fastapi`` 各一遍。测试想知道自己跑在哪一层时就要这个 fixture。"""
    return request.param


@pytest.fixture
async def layer(stack):
    """The started layer: ``(graph root, ASGI application)``.

    两层在这里的差别一眼能看见：canary 层的应用单元自己就是根、也就是那个 ASGI 应用；
    fastapi 层的根是 ``Services``，应用要另外 ``create_app(root)``。
    """
    async with running_stack(stack) as started:
        yield started


@pytest.fixture
def root(layer):
    """The graph's root unit —— 两层都有，业务那张图是同一份。"""
    return layer[0]


@pytest.fixture
def app(layer):
    """This layer's ASGI application."""
    return layer[1]


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with connect(app) as http:
        yield http


@pytest.fixture
def database(root) -> Database:
    """The live ``Database`` unit, for tests that need to age rows directly."""
    return unit(root, Database)


# -- 单栈：只属于某一层的测试用它 ------------------------------------------


@pytest.fixture
async def canary_client() -> AsyncIterator[httpx.AsyncClient]:
    async with running_stack("canary") as (_root, app), connect(app) as http:
        yield http


@pytest.fixture
async def fastapi_client() -> AsyncIterator[httpx.AsyncClient]:
    async with running_stack("fastapi") as (_root, app), connect(app) as http:
        yield http

"""Fixtures —— 同一套行为测试，对两层 HTTP 各跑一遍。

``stack`` 这个 fixture 被参数化成 ``fastapi`` 与 ``web``，而 ``root`` / ``client`` /
``database`` 都依赖它，所以**每个用到 client 的测试都会跑两遍**：一遍打 FastAPI 版的应用，
一遍打 web 版的应用。两层只是 HTTP，业务是同一份，所以它们的答案必须一样——不一样的地方
就是这一轮要找的东西。

只属于某一层的东西（OpenAPI 与 ``/docs``、web 的 405/HEAD 细节）在
``tests/test_stack_fastapi.py`` 与 ``tests/test_stack_web.py`` 里，用单栈的 fixture。

``AppConfig`` 默认 ``storage=sqlite`` + ``sqlite_path=":memory:"``，``Database`` 又把内存
库钉在单条连接上，所以每个测试拿到一份私有 schema，随应用一起消失。请求不经网络也不要
服务器：``httpx.ASGITransport`` 直接调 ``root.app``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from canary_framework.test import running, unit

from app.api import NAMES, application
from app.api import stack as stack_module
from app.infra.db import Database


def connect(api) -> httpx.AsyncClient:
    """An HTTP client talking straight to an application unit, no socket in between."""
    transport = httpx.ASGITransport(app=api.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(params=NAMES)
def stack(request) -> str:
    """``fastapi`` 与 ``web`` 各一遍。测试想知道自己跑在哪一层时就要这个 fixture。"""
    return request.param


@pytest.fixture
def layer(stack):
    """The module implementing the current stack —— 它给出 ``LibraryApi`` / ``Api`` / 各路由单元。

    两层的类是**不同的类**（``app.api.fastapi.CatalogApi`` 与 ``app.api.web.CatalogApi``），
    所以断言依赖图的测试要从这里取类，而不是直接 import。
    """
    return stack_module(stack)


@pytest.fixture
async def root(stack):
    """A started application unit of the current stack; 退出时整张图逆序回收。"""
    async with running(application(stack)) as api:
        yield api


@pytest.fixture
async def client(root) -> AsyncIterator[httpx.AsyncClient]:
    async with connect(root) as http:
        yield http


@pytest.fixture
def database(root) -> Database:
    """The live ``Database`` unit, for tests that need to age rows directly."""
    return unit(root, Database)


# -- 单栈：只属于某一层的测试用它 ------------------------------------------


@pytest.fixture
async def fastapi_client() -> AsyncIterator[httpx.AsyncClient]:
    async with running(application("fastapi")) as api, connect(api) as http:
        yield http


@pytest.fixture
async def web_client() -> AsyncIterator[httpx.AsyncClient]:
    async with running(application("web")) as api, connect(api) as http:
        yield http

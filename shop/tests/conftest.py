"""Fixtures —— 已有应用 + 一张图，每个测试一份。

和另外两个场景的区别全在这里：这里**没有** ``running(Root)``，因为根单元不是进程的
主人。驱动生命周期的是 ASGI 的 lifespan，所以测试也照着驱动它：

    async with app.router.lifespan_context(app):
        ...

这就是 uvicorn 做的事，不多也不少。``httpx.ASGITransport`` 自己不驱动 lifespan，所以
这一句不能省——省了的话图没启动，新接口会 503（见 test_framework_boundaries.py）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from shop import legacy
from shop.asgi import create_app


@pytest.fixture(autouse=True)
def clean_legacy_state() -> None:
    """The old code keeps its orders in a module-level dict —— 测试之间要洗掉。

    这正是老代码的样子，也正是迁移要解决的事：图上的单元每次 ``running`` 都是新的，
    模块级的状态不是。
    """
    legacy._ORDERS.clear()


@pytest.fixture
def app() -> FastAPI:
    """A fresh application object. 不要共用——``mount()`` 没有反操作。"""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The application with its graph running, driven the way uvicorn drives it."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http

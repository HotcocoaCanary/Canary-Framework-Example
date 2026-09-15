"""Fixtures — a fully assembled application per test, on its own in-memory DB.

``AppConfig`` 默认 ``storage=sqlite`` + ``sqlite_path=":memory:"``，``Database`` 又把内存
库钉在单条连接上，所以每个测试拿到一份私有 schema，随应用一起消失。不需要任何外部服务：
嵌入与对话模型默认都是离线确定性实现。

``TestClient`` 的上下文管理器驱动 ASGI lifespan，lifespan 再驱动 Canary 那张图——
两层生命周期的对接点只有 ``app/wiring.py`` 里那三行。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def client():
    """A started application; 退出时整张图逆序回收。"""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def root(client):
    """The composition root behind the running app."""
    return client.app.state.root


@pytest.fixture
def database(root):
    """The live ``Database`` unit, for tests that need to age rows directly."""
    from app.infra.db import Database
    from app.testing import unit

    return unit(root, Database)

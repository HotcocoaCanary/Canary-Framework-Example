"""Fixtures —— 每个测试一条新流水线，两层 HTTP 各跑一遍。

``stack`` 被参数化成 ``fastapi`` 与 ``web``，``pipe`` / ``client`` / ``app_client`` 都依赖
它。HTTP 在这条流水线上只是接入口，队列、消费者、账本、两个停机阶段全是共用的业务，
所以两层的答案必须一样。

三种粒度都在用：

* ``pipe`` / ``client``：``port = 0`` 的真实套接字，压的是"HTTP 与消费者同进程"；
* ``app_client``：只启动 ``IngestApp``，用 ``ASGITransport`` 打它的 ``self.app``——没有
  服务器、没有端口，但消费者仍然在跑（它们是应用的依赖的依赖）；
* 直接 ``await processor.run(job)``：纯业务，不要图以外的任何东西。

配置、``started()``、``settle()`` 在 ``pipeline/testing.py`` 里，几个测试文件共用。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from pipeline.http import NAMES
from pipeline.http import root as root_class
from pipeline.http import stack as stack_module
from pipeline.testing import started


@pytest.fixture(params=NAMES)
def stack(request) -> str:
    """``fastapi`` 与 ``web`` 各一遍。"""
    return request.param


@pytest.fixture
def layer(stack):
    """The module implementing the current stack —— 它给出这一层的应用单元与根单元。"""
    return stack_module(stack)


@pytest.fixture
async def pipe(stack: str):
    """The whole process: one listening port, two lanes, two extra phases."""
    async with started(root_class(stack)) as unit:
        yield unit


@pytest.fixture
async def client(pipe) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the real port."""
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as http:
        yield http


@pytest.fixture
async def app_client(layer) -> AsyncIterator[httpx.AsyncClient]:
    """The application alone: no server, no socket —— but the lanes are still running.

    消费者不是服务器的依赖，是应用的依赖（``StatusApi`` 读它们），所以这张图里照常启动。
    "要不要监听"和"要不要后台消费"是两件独立的事。
    """
    async with started(layer.IngestApp) as app:
        transport = httpx.ASGITransport(app=app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://app") as http:
            yield http

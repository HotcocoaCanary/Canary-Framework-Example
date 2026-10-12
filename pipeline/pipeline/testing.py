"""Test helpers shipped with the package.

随包发布的测试辅助。放在包里而不是 ``tests/`` 下，是为了几个场景都能有一个叫 ``tests/``
的目录而不在 import 时撞车。

启动一张图、换配置、按类型取单元，全都用框架自带的 ``canary_framework.test``；这里只剩
这条流水线自己的东西——配置的测试默认值，以及"等任务做完"。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from canary_framework import Canary
from canary_framework.test import running, unit

from pipeline.jobs import DONE, FAILED, JobBook
from pipeline.settings import PipelineSettings


def settings(**overrides: Any) -> PipelineSettings:
    """Test settings: a system-assigned port, small lanes, short budgets.

    测试用的配置：端口交给系统分配（``port = 0``），通道小一点，预算短一点。
    """
    values: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 0,
        "lane_workers": {"fast": 2, "bulk": 1},
        "queue_size": 64,
        "bulk_threshold": 50,
        "drain_timeout_seconds": 5.0,
        "max_attempts": 3,
        "row_seconds": 0.0,
    }
    values.update(overrides)
    return PipelineSettings(**values)


@asynccontextmanager
async def started[T: Canary](root: type[T], **overrides: Any) -> AsyncIterator[T]:
    """Start *root* on test settings —— 一张新图，退出时回收。

    *root* 要显式给出：两层 HTTP 各有一个 ``Pipeline``（``pipeline.http.root(stack)`` 取），
    因为 ``dep()`` 是写在类上的声明。

    配置是用**替身**换的：``running`` 的第二个参数经 ``Scope.provide`` 登记，所以真的
    ``PipelineSettings`` 连构造都不会发生。
    """
    async with running(root, {PipelineSettings: settings(**overrides)}) as started_unit:
        yield started_unit


def rows(count: int, start: int = 1000, amount: int = 100) -> list[dict[str, Any]]:
    """*count* 行能被接受的流水。"""
    return [
        {"account": str(start + index), "amount_cents": amount, "ref": f"r{index}"}
        for index in range(count)
    ]


async def settle(graph: Canary, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Wait until *job_id* is finished, reading the graph rather than HTTP.

    等到任务不在途了。读的是图上的 ``JobBook``，不是 HTTP——时间驱动的东西要能被等，
    否则测试只能靠 sleep 猜。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    book = unit(graph, JobBook)
    while loop.time() < deadline:
        job = book.get(job_id)
        assert job is not None, f"{job_id} 不在台账里"
        if job.state in (DONE, FAILED):
            return job.view()
        await asyncio.sleep(0.005)
    raise AssertionError(f"{job_id} 没有在 {timeout}s 内结束")

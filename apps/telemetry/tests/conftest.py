"""Fixtures — a fully assembled daemon on a hand-advanced clock.

Nothing here sleeps.  The whole point of scenario 2 is a *time*-driven system,
and a time-driven system is only testable if the test owns the clock.

最终版删掉了 ``provide=``，所以"拥有时钟"这件事由 ``telemetry/testing.py`` 自己做：
在 ``init()`` 与 ``start()` 之间把注入好的 ``Clock`` 换掉。见那个模块的说明。
"""

from __future__ import annotations

import pytest

from canary_framework import Canary
from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import ManualClock
from telemetry.testing import apply_settings, swap_clock


@pytest.fixture
def runtime() -> Canary:
    """An un-started runtime — for tests that drive the lifecycle themselves."""
    return Canary(TelemetryDaemon)


@pytest.fixture
async def daemon(runtime: Canary):
    """A started daemon: manual clock, deterministic synthetic samples."""
    await runtime.init()
    runtime.manual_clock = swap_clock(runtime)
    await runtime.start()

    # 调度器的循环在这些测试里是噪声：作业由测试直接调用。
    await runtime[TelemetryDaemon].supervised_tasks.shutdown()

    yield runtime[TelemetryDaemon]
    await runtime.stop()


@pytest.fixture
def clock(runtime: Canary, daemon) -> ManualClock:
    """The swapped-in clock. ``canary[Clock]`` 仍然是真时钟——框架不知道换过。"""
    return runtime.manual_clock

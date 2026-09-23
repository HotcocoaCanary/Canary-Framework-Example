"""Fixtures — a fully assembled daemon on a hand-advanced clock.

Nothing here sleeps.  场景二的全部意义是一个*时间*驱动的系统，而时间驱动的系统只有在
测试拥有时钟时才可测。

"拥有时钟"这件事是用 ``Scope.provide`` 把 ``ManualClock`` 登记进作用域，真 ``Clock`` 因此
连构造都不会发生——见 ``telemetry/testing.py`` 的说明。
"""

from __future__ import annotations

import pytest

from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import ManualClock
from telemetry.testing import started_daemon


@pytest.fixture
async def started(request) -> tuple[TelemetryDaemon, ManualClock]:
    """A started daemon; ``@pytest.mark.settings(...)`` 可覆盖任意配置字段。"""
    marker = request.node.get_closest_marker("settings")
    daemon, clock = await started_daemon(**(marker.kwargs if marker else {}))

    # 调度器的后台循环在绝大多数测试里是噪声：作业由测试直接调用。
    await daemon.tasks.shutdown()

    yield daemon, clock
    await daemon.stop()


@pytest.fixture
def daemon(started) -> TelemetryDaemon:
    return started[0]


@pytest.fixture
def clock(started) -> ManualClock:
    return started[1]

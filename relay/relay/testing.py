"""Test doubles shipped with the package.

随包发布的替身。放在包里而不是 ``tests/`` 下，是为了几个场景都能有一个叫 ``tests/`` 的
目录而不在 import 时撞车。

替身走 ``running(Relay, {Clock: ManualClock()})`` 登记：被替换的单元**不会被构造**，替身
按自身的类型参与生命周期。所以替身必须是被替换类型的子类实例，否则在任何单元启动之前就
抛 ``TypeError``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from canary_framework import Canary

from relay.clock import Clock


class ManualClock(Clock):
    """A clock that only moves when the test moves it.

    只有测试推它才会走的时钟。
    """

    def __init__(self, start: datetime | None = None) -> None:
        self.at = start or datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
        self.ticks = 0.0

    def now(self) -> datetime:
        return self.at

    def monotonic(self) -> float:
        return self.ticks

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)
        self.ticks += seconds


@asynccontextmanager
async def running_api(name: str, doubles: dict | None = None) -> AsyncIterator[tuple[Canary, Any]]:
    """Start just the public application of one layer, and yield ``(root, ASGI app)``.

    只启动"对外那个应用"，不要服务器、不要端口。两层在这里的差别一眼能看见：

    * canary 层：应用单元自己就是根，**也**就是那个 ASGI 应用；
    * fastapi 层：没有应用单元，所以根取 ``Fleet``（台账那张子图），应用要用
      ``create_public(root)`` 另外建，并把图挂到它身上（那座桥）。

    代价也在这里：fastapi 层的"图的根"得自己挑一个单元——没有应用单元替它拢住那张图。
    """
    from canary_framework.test import running

    from relay.fleet import Fleet
    from relay.http import stack as stack_module

    module = stack_module(name)
    if name == "canary":
        async with running(module.PublicApi, doubles) as api:
            yield api, api
    else:
        async with running(Fleet, doubles) as fleet:
            yield fleet, module.create_public(fleet)

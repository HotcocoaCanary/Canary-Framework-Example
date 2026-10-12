"""Test doubles shipped with the package.

随包发布的替身。放在包里而不是 ``tests/`` 下，是为了几个场景都能有一个叫 ``tests/`` 的
目录而不在 import 时撞车。

替身走 ``running(Relay, {Clock: ManualClock()})`` 登记：被替换的单元**不会被构造**，替身
按自身的类型参与生命周期。所以替身必须是被替换类型的子类实例，否则在任何单元启动之前就
抛 ``TypeError``。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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

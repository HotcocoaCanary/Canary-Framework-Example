"""Time source — the real one, and the hand-advanced one tests substitute for it.

最终版的框架没有替换入口，所以这条缝由测试自己搭：``telemetry/testing.py::swap_clock``
在 ``init()`` 与 ``start()`` 之间把注入好的 ``Clock`` 换成 ``ManualClock``——注入已经
发生、``@on_start`` 还没跑，那一刻是唯一的窗口。

``ManualClock`` 故意不是 ``@cocoa``：替身不必是单元。它继承 ``Clock`` 只是为了让类型
检查器在声明 ``Clock`` 的地方接受它。
"""

from __future__ import annotations

import time

from canary_framework import cocoa


@cocoa
class Clock:
    """Wall-clock time."""

    def now(self) -> float:
        return time.time()


class ManualClock(Clock):
    """A clock that only moves when a test moves it."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += seconds
        return self._now

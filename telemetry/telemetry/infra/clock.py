"""Time source — the real one, and the hand-advanced one tests put in its place.

``ManualClock`` 继承 ``Clock``，因此它本身也是一个单元。测试用 ``Scope.provide`` 把它
登记进作用域（见 ``telemetry.testing``），``dep(Clock)`` 于是取回它，真时钟连构造都不会发生——
0.9.x 的替换缝做不到这一点，那时真单元照样实例化、照样跑 ``@on_start``。

继承带来一个后果：子类同时继承父类的钩子。``Clock`` 目前没有钩子；将来若加了，
``ManualClock`` 覆盖同名方法即可挡掉——钩子按属性名解析，覆盖就是覆盖。
"""

from __future__ import annotations

import time

from canary_framework import Canary


class Clock(Canary):
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

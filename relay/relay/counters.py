"""Process-wide counters.

进程级计数器。被两个端口上的三个应用共用：公网 API 写、``/metrics`` 读、管理口也读同一份
——因为 ``Counters`` 在图上只有一个实例，而 ``Metrics`` 应用单元被两个 ``Server`` 依赖。
"""

from __future__ import annotations

from collections import Counter

from canary_framework import Canary


class Counters(Canary):
    """A tiny counter registry, enough for a Prometheus text exposition.

    够 ``/metrics`` 用的最小计数器表。
    """

    values: Counter[str]

    def __init__(self) -> None:
        # 单元一律无参构造，所以 ``__init__`` 想写就写——框架只要求它不需要参数。
        self.values = Counter()

    def incr(self, name: str, amount: int = 1) -> None:
        self.values[name] += amount

    def value(self, name: str) -> int:
        return self.values[name]

    def snapshot(self) -> dict[str, int]:
        return dict(self.values)

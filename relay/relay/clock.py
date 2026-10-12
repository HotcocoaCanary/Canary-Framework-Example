"""The clock, as a unit — so that time can be replaced in tests.

时钟是一个单元，于是测试里可以用替身推时间。``Reaper`` 的超时判断、心跳的时间戳都从这里读，
没有任何地方直接调 ``time.time()``。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from canary_framework import Canary


class Clock(Canary):
    """Wall-clock time. Replace it with a double to test anything time-dependent.

    真实时钟。测试里用 ``running(Relay, {Clock: ManualClock()})`` 换掉它。
    """

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

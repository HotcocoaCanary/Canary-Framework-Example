"""Test helpers shipped with the package — see ``app/testing.py`` in scenario 1.

**替换缝在这里，不在框架里。** 最终版删掉了 ``Canary(provide=...)``：图上的实例
全部由框架无参构造，运行时没有任何入口能把另一个对象放到某个单元的位置上。

于是这个文件替框架做那件事。可行的原因是注入现在发生在 ``init()``：
``init()`` 之后依赖已经挂在每个单元身上，而 ``@on_start`` 还没跑——这中间的空档
就是唯一的缝，把注入好的 ``Clock`` 换成手动时钟，把共享的 ``AppConfig``
按测试的需要改几个字段。

代价：框架不再知道这件事发生过（``canary[Clock]`` 仍然返回真时钟），
所以手动时钟要由这里交回给调用者。
"""

from __future__ import annotations

from canary_framework import Canary

from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import Clock, ManualClock
from telemetry.settings import AppConfig


def swap_clock(app: Canary) -> ManualClock:
    """Replace the injected ``Clock`` on every unit that got one. Call between init and start."""
    manual = ManualClock()
    for unit in app.instances:
        if isinstance(getattr(unit, "clock", None), Clock):
            unit.clock = manual
    return manual


def apply_settings(app: Canary, **settings) -> AppConfig:
    """Change fields on the shared ``AppConfig``. 整张图拿的是同一个对象，改它就够了。"""
    config = app[AppConfig]
    for name, value in settings.items():
        assert hasattr(config, name), f"AppConfig 没有字段 {name}"
        setattr(config, name, value)
    return config


async def started_runtime(**settings) -> tuple[Canary, ManualClock]:
    """A started daemon on a hand-advanced clock, with any settings the test wants changed.

    时间必须由测试拥有：整套管线测试因此一次 ``sleep`` 都不需要。
    """
    app = Canary(TelemetryDaemon)
    await app.init()
    apply_settings(app, **settings)
    clock = swap_clock(app)
    await app.start()
    return app, clock


async def collect_for(daemon, clock, *, seconds: float, step: float = 2.0) -> int:
    """Advance the clock in *step* increments, collecting a sample each time."""
    ticks = int(seconds / step)
    for _ in range(ticks):
        await daemon.collector_daemon.collect_once()
        clock.advance(step)
    return ticks

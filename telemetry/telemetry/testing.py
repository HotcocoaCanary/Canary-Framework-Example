"""Test helpers — substituting units with ``Scope.provide``.

替换一个单元用框架自带的 ``Scope.provide``：在生命周期开始之前登记替身，整张图的
``dep(Clock)`` 取回的就是它::

    daemon = TelemetryDaemon()
    scope_of(daemon).provide(Clock, ManualClock())
    async with daemon: ...

和 0.9.x 的 ``setattr`` 缝相比有两处实打实的改善：

1. **真单元根本不会被构造。** 旧缝是在图建好之后逐个改属性，被替掉的那棵子树照样
   实例化、照样跑 ``@on_start``——换掉仓储也拦不住它的依赖去连数据库。现在作用域里
   已经有实例，构造那一步直接不发生。
2. **替身是图上的一等公民。** 它照常进台账、照常跑自己的钩子、推进自己声明的依赖、
   被 ``stop()`` 回收。旧缝里替身的钩子永远不跑，持有资源的替身得自己开关。

替身必须是被替换类的实例——``provide`` 会检查。
"""

from __future__ import annotations

from canary_framework import Canary, scope_of

from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import Clock, ManualClock
from telemetry.settings import AppConfig


async def started_daemon(**settings: object) -> tuple[TelemetryDaemon, ManualClock]:
    """A started daemon on a hand-advanced clock, with any settings the test changed.

    时间必须由测试拥有：整套管线测试因此一次 ``sleep`` 都不需要。

    配置也用 ``provide`` 登记：``AppConfig`` 是 ``BaseSettings`` 与 ``Canary`` 的混合，所以
    "按测试需要构造一个配置"就是普通的 pydantic 用法，不需要先启动再改字段。
    """
    daemon = TelemetryDaemon()
    scope = scope_of(daemon)
    scope.provide(AppConfig, AppConfig(**settings))  # type: ignore[arg-type]
    clock = ManualClock()
    scope.provide(Clock, clock)
    await daemon.init()
    await daemon.start()
    return daemon, clock


def unit[T: Canary](root: Canary, cls: type[T]) -> T:
    """The scope's instance of *cls* — 0.9.x 里 ``canary[Type]`` 的替代写法。

    运行时容器没有了，取而代之的是作用域本身：``scope_of(root).instances`` 就是
    "类型 → 实例"那张表。日常代码应当从声明它的单元上读（``daemon.collector.store``），
    这个 helper 只给测试用——测试常常要够到一个自己没声明过依赖的单元。
    """
    return scope_of(root).instances[cls]  # type: ignore[return-value]


async def collect_for(
    daemon: TelemetryDaemon, clock: ManualClock, *, seconds: float, step: float = 2.0
) -> int:
    """Advance the clock in *step* increments, collecting a sample each time."""
    ticks = int(seconds / step)
    for _ in range(ticks):
        await daemon.collector.collect_once()
        clock.advance(step)
    return ticks

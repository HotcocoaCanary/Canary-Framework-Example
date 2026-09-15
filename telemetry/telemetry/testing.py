"""Test helpers — how you substitute a unit when the framework has no ``provide=``.

0.10.0 里替换一个单元靠的是**作用域预登记**，而不是替换入口：

``Scope.instances`` 是"类型 → 本作用域内的唯一实例"。``dep(Clock)`` 读取时走的正是
``scope.instance(Clock)``，它只在表里没有时才无参构造。所以只要在生命周期开始之前
把替身放进那张表，整张图拿到的就是替身::

    daemon = TelemetryDaemon()
    seed(scope_of(daemon), Clock, ManualClock())
    async with daemon: ...

和 0.9.x 的 ``setattr`` 缝相比有两处实打实的改善：

1. **真单元根本不会被构造。** 旧缝是在图建好之后逐个改属性，被替掉的那棵子树照样
   实例化、照样跑 ``@on_start``——换掉仓储也拦不住它的依赖去连数据库。现在表里已经
   有实例，构造那一步直接不发生。
2. **替身是图上的一等公民。** 它照常进台账、照常跑自己的钩子、照常被 ``stop()`` 回收。
   旧缝里替身的钩子永远不跑，持有资源的替身得自己开关。

代价是替身要么继承被替的类，要么至少鸭子兼容——``seed`` 不做类型检查，登记的是哪个
键就按哪个键取。
"""

from __future__ import annotations

from canary_framework import Canary, Scope, scope_of

from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import Clock, ManualClock
from telemetry.settings import AppConfig


def seed[T: Canary](scope: Scope, cls: type[Canary], instance: T) -> T:
    """Register *instance* as *scope*'s instance of *cls*, before the lifecycle starts.

    ``adopt`` 把作用域写到替身身上（这样替身自己声明的依赖也解析得了），再按 *cls*
    这个键登记一次——``adopt`` 登记用的是 ``type(instance)``，而依赖声明的是 *cls*。
    """
    scope.adopt(instance)
    scope.instances[cls] = instance
    return instance


async def started_daemon(**settings: object) -> tuple[TelemetryDaemon, ManualClock]:
    """A started daemon on a hand-advanced clock, with any settings the test changed.

    时间必须由测试拥有：整套管线测试因此一次 ``sleep`` 都不需要。

    配置也走预登记：``AppConfig`` 是 ``BaseSettings`` 与 ``Canary`` 的混合，所以
    "按测试需要构造一个配置"就是普通的 pydantic 用法，不需要先启动再改字段。
    """
    daemon = TelemetryDaemon()
    scope = scope_of(daemon)
    seed(scope, AppConfig, AppConfig(**settings))  # type: ignore[arg-type]
    clock = seed(scope, Clock, ManualClock())
    await daemon.init()
    await daemon.start()
    return daemon, clock


def unit[T: Canary](root: Canary, cls: type[T]) -> T:
    """The scope's instance of *cls* — 0.10.0 里 ``canary[Type]`` 的替代写法。

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

"""Executable notes on canary-framework 0.10.0, written from the daemon's side.

守护进程形态压得到 HTTP 应用压不到的地方：uvicorn 拥有生命周期时，启动失败只是打死
进程；守护进程自己拥有生命周期，框架的失败语义与回收语义就成了承重墙。

这一版把 0.9.x 时代的一批断言整个换掉了——``@cocoa``、``Canary(*roots)`` 容器、
``LifecycleState`` 八态状态机、``provide=``、按类名 snake_case 注入全部不存在了。
下面钉的是 0.10.0 **真正**的行为，以及它相对 0.9.x 修好的地方。
"""

from __future__ import annotations

import asyncio

import pytest
from canary_framework import (
    Canary,
    CircularDependencyError,
    ConstructionError,
    DeclarationError,
    LifecycleError,
    Phase,
    advance,
    dep,
    deps_of,
    init,
    scope_of,
    start,
    stop,
)

log: list[str] = []


@pytest.fixture(autouse=True)
def _clear_log():
    log.clear()
    yield


# --- 声明 --------------------------------------------------------------


async def test_dep_rejects_a_non_unit_at_class_body_time():
    """``dep()`` 在类体求值那一刻就检查，错误指向写下它的那一行，不必等到运行。"""
    with pytest.raises(DeclarationError, match="not a Canary subclass"):

        class Bad(Canary):
            oops = dep(dict)  # type: ignore[type-var]


async def test_the_attribute_name_is_yours_and_the_type_is_inferred():
    """0.9.x 的注入名是被依赖类名的 snake_case；现在由使用者决定。"""

    class VeryLongImplementationName(Canary):
        value = 7

    class User(Canary):
        thing = dep(VeryLongImplementationName)  # 抽象的名字

    async with User() as user:
        assert user.thing.value == 7
        assert not hasattr(user, "very_long_implementation_name")


async def test_two_attributes_pointing_at_one_type_are_one_dependency():
    class Shared(Canary):
        pass

    class User(Canary):
        left = dep(Shared)
        right = dep(Shared)

    assert deps_of(User) == (Shared,)
    async with User() as user:
        assert user.left is user.right


async def test_declarations_survive_from_future_annotations():
    """描述符持有类对象本身，不需要求值——0.9.x 的类级注解注入在这里会静默失效。"""
    from tests import _future_annotations_unit as module

    async with module.Consumer() as consumer:
        assert consumer.provider.value == "ok"


# --- 构造 --------------------------------------------------------------


async def test_a_unit_that_needs_constructor_arguments_is_told_where_to_put_them():
    """单元一律由框架无参构造，错误信息只给得出一条出路。"""

    class Settings(Canary):
        dsn = "postgres://x"

    class Engine(Canary):
        settings = dep(Settings)

        def __init__(self, pool_size: int) -> None:
            self.pool_size = pool_size

    class Service(Canary):
        engine = dep(Engine)

    with pytest.raises(ConstructionError) as caught:
        await Service().init()
    message = str(caught.value)
    assert "dep(" in message
    assert "@init" in message or "@start" in message


async def test_reading_a_dependency_before_the_lifecycle_begins_is_refused():
    """依赖从 ``@init`` 起才可用；在 ``__init__`` 里读会抛 ``LifecycleError``。"""

    class Provider(Canary):
        pass

    class TooEager(Canary):
        provider = dep(Provider)

        def __init__(self) -> None:
            self.stolen = self.provider  # 生命周期还没开始

    with pytest.raises(LifecycleError, match="before the lifecycle begins"):
        await TooEager().init()


async def test_a_cycle_reports_the_path_it_actually_walked():
    class A(Canary):
        pass

    class B(Canary):
        a = dep(A)

    A.b = dep(B)  # type: ignore[attr-defined]
    A.b.__set_name__(A, "b")  # type: ignore[attr-defined]

    with pytest.raises(CircularDependencyError) as caught:
        await A().init()
    assert caught.value.cycle[0] is caught.value.cycle[-1]


# --- 阶段与栅栏 ---------------------------------------------------------


async def test_every_init_finishes_before_any_start_runs():
    """全部 ``@init`` 完成之后，才有任何 ``@start`` 运行——这是一道全图栅栏。"""

    class Dependency(Canary):
        @init
        async def i(self) -> None:
            log.append("dep.init")

        @start
        async def s(self) -> None:
            log.append("dep.start")

    class Root(Canary):
        dependency = dep(Dependency)

        @init
        async def i(self) -> None:
            log.append("root.init")

        @start
        async def s(self) -> None:
            log.append("root.start")

    async with Root():
        pass
    assert log == ["dep.init", "root.init", "dep.start", "root.start"]


async def test_a_fourth_phase_needs_no_registration():
    """``Phase("migrate")`` 就是第四个阶段，不必向框架登记。"""
    migrate = Phase("migrate", after=init)

    class Schema(Canary):
        @migrate
        async def apply(self) -> None:
            log.append("migrated")

    schema = Schema()
    await schema.init()
    await advance(schema, migrate)
    assert log == ["migrated"]


async def test_overriding_a_hook_replaces_it_instead_of_adding_to_it():
    """钩子按属性名解析，语义与普通方法一致——0.9.x 按函数身份去重，覆盖变成了叠加。"""

    class Base(Canary):
        @start
        async def go(self) -> None:
            log.append("base")

    class Child(Base):
        @start
        async def go(self) -> None:
            log.append("child")

    async with Child():
        pass
    assert log == ["child"]


async def test_super_composes_when_you_want_both():
    class Base(Canary):
        @start
        async def go(self) -> None:
            log.append("base")

    class Child(Base):
        @start
        async def go(self) -> None:
            await super().go()
            log.append("child")

    async with Child():
        pass
    assert log == ["base", "child"]


async def test_lifecycle_methods_themselves_can_be_overridden():
    """本项目的 ``TelemetryDaemon.start`` 正是这个形状。"""

    class Traced(Canary):
        async def start(self) -> None:
            log.append("before")
            await super().start()
            log.append("after")

    async with Traced():
        pass
    assert log == ["before", "after"]


# --- 失败与回收 ---------------------------------------------------------


async def test_a_failed_start_releases_everything_it_had_acquired():
    """已启动的单元按逆序回收，**含失败单元自身**，原异常原样抛出。

    这条对本项目是硬需求：``SupervisedTasks`` / ``SampleSource`` / ``LoggingAlertSink``
    都在 ``@start`` 里拿资源。
    """

    class Acquires(Canary):
        @start
        async def s(self) -> None:
            log.append("Acquires.start")

        @stop
        async def t(self) -> None:
            log.append("Acquires.stop")

    class HalfStarted(Canary):
        acquires = dep(Acquires)

        @start
        async def s(self) -> None:
            log.append("HalfStarted.start")
            raise RuntimeError("启动失败")

        @stop
        async def t(self) -> None:
            # 失败单元自己也在台账上，所以这个钩子会跑——它必须容忍
            # 「@start 只跑了一半」的自己。
            log.append("HalfStarted.stop")

    unit = HalfStarted()
    await unit.init()
    with pytest.raises(RuntimeError, match="启动失败"):
        await unit.start()
    await unit.stop()

    assert log == [
        "Acquires.start",
        "HalfStarted.start",
        "HalfStarted.stop",  # 失败的那个先回收
        "Acquires.stop",
    ]


async def test_async_with_rolls_back_on_a_failed_start():
    class Acquires(Canary):
        @start
        async def s(self) -> None:
            log.append("acquire")

        @stop
        async def t(self) -> None:
            log.append("release")

    class Fails(Canary):
        acquires = dep(Acquires)

        @start
        async def s(self) -> None:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        async with Fails():
            pass
    assert log == ["acquire", "release"]


async def test_stop_is_idempotent_and_reclaims_only_once():
    class Unit(Canary):
        @stop
        async def t(self) -> None:
            log.append("stop")

    unit = Unit()
    async with unit:
        pass
    await unit.stop()
    await unit.stop()
    assert log == ["stop"]


async def test_stop_before_start_is_a_no_op():
    """从未启动过的图没有台账，回收是空操作——不会凭空跑 ``@stop``。"""

    class Unit(Canary):
        @init
        def prepare(self) -> None:
            log.append("init")

        @stop
        async def release(self) -> None:
            log.append("stop")

    fresh = Unit()
    await fresh.stop()
    assert log == []

    inited = Unit()
    await inited.init()
    await inited.stop()
    assert log == ["init"], "@init 没进 start 台账，所以没有对应的回收步骤"


async def test_a_failing_stop_hook_no_longer_strands_the_ones_below_it():
    """最底层的连接池 / 后台任务照样被回收，异常合并成 ExceptionGroup。"""

    class Innermost(Canary):
        @stop
        async def t(self) -> None:
            log.append("Innermost.stop")

    class BadStop(Canary):
        innermost = dep(Innermost)

        @stop
        async def t(self) -> None:
            log.append("BadStop.stop")
            raise RuntimeError("关停失败")

    class Outermost(Canary):
        bad_stop = dep(BadStop)

        @stop
        async def t(self) -> None:
            log.append("Outermost.stop")

    unit = Outermost()
    await unit.init()
    await unit.start()

    with pytest.raises(ExceptionGroup) as caught:
        await unit.stop()

    assert log == ["Outermost.stop", "BadStop.stop", "Innermost.stop"]
    assert [type(e) for e in caught.value.exceptions] == [RuntimeError]
    # 异常带上了出处，否则 ExceptionGroup 里认不出是谁抛的
    assert any("BadStop" in n for n in getattr(caught.value.exceptions[0], "__notes__", []))


async def test_stop_collects_every_failure_not_just_the_first():
    class BadA(Canary):
        @stop
        async def t(self) -> None:
            raise RuntimeError("A")

    class BadB(Canary):
        bad_a = dep(BadA)

        @stop
        async def t(self) -> None:
            raise RuntimeError("B")

    unit = BadB()
    await unit.init()
    await unit.start()
    with pytest.raises(ExceptionGroup) as caught:
        await unit.stop()
    assert {str(e) for e in caught.value.exceptions} == {"A", "B"}


async def test_a_failure_during_rollback_rides_along_as_a_note():
    """回收自身失败不改变异常类型，也不吞掉原因——附成 note。"""

    class BadCleanup(Canary):
        @stop
        async def t(self) -> None:
            raise RuntimeError("回收也失败了")

    class Fails(Canary):
        bad_cleanup = dep(BadCleanup)

        @start
        async def s(self) -> None:
            raise ValueError("原始失败")

    with pytest.raises(ValueError, match="原始失败") as caught:
        async with Fails():
            pass

    notes = getattr(caught.value, "__notes__", [])
    assert any("回收也失败了" in note for note in notes), notes


async def test_an_init_failure_leaves_nothing_to_reclaim():
    class BadInit(Canary):
        @init
        async def boom(self) -> None:
            raise RuntimeError("init 失败")

        @stop
        async def t(self) -> None:
            log.append("BadInit.stop")

    unit = BadInit()
    with pytest.raises(RuntimeError, match="init 失败"):
        await unit.init()
    await unit.stop()
    assert log == []


# --- 替换：Scope.provide ----------------------------------------------------


async def test_the_substitution_seam_is_scope_provide():
    """本项目整套管线测试靠这条缝把 ``Clock`` 换成手动时钟。

    和 0.9.x 的 ``setattr`` 缝相比，真单元这次**根本不会被构造**。
    """
    built: list[str] = []

    class Expensive(Canary):
        def __init__(self) -> None:
            built.append("real")

        @start
        async def connect(self) -> None:
            built.append("connected")

    class Fake(Expensive):
        def __init__(self) -> None:  # 故意不调 super()
            pass

        @start
        async def connect(self) -> None:  # 覆盖掉真实现的钩子
            built.append("fake connected")

    class Service(Canary):
        expensive = dep(Expensive)

    service = Service()
    fake = Fake()
    scope_of(service).provide(Expensive, fake)

    async with service:
        assert service.expensive is fake
    assert built == ["fake connected"], "真单元既没被构造，也没被启动"


async def test_a_provided_substitute_is_reclaimed_like_any_other_unit():
    """替身是图上的一等公民：进台账、跑自己的钩子、被 ``stop()`` 回收。"""

    class Real(Canary):
        pass

    class Fake(Real):
        @stop
        async def t(self) -> None:
            log.append("fake.stop")

    class Service(Canary):
        real = dep(Real)

    service = Service()
    fake = Fake()
    scope_of(service).provide(Real, fake)

    async with service:
        pass
    assert log == ["fake.stop"]


# --- 框架仍然不提供的东西 -------------------------------------------------


async def test_there_is_still_no_scheduler_or_task_facility():
    """本项目仍然要自带 ``SupervisedTasks`` 与 ``Scheduler``。

    0.10.0 的核心只做两件事：依赖注入与生命周期。这不是缺陷，是范围——但用它写守护
    进程的人都要自己补这两块，所以记在这里。
    """
    public = {name for name in vars(Canary) if not name.startswith("_")}
    assert public == {"init", "start", "stop"}
    assert not any(k in name for name in public for k in ("task", "sched", "timer", "job"))


async def test_there_is_no_after_all_hook_out_of_the_box():
    """"全图起来之后"没有内建位置——但加一个阶段就有了，代价是三行。

    这正是 ``telemetry/phases.py`` 的全部内容。0.9.x 里同样的需求只能靠"根排在拓扑序
    最后"这条未文档化的性质。
    """
    launch = Phase("launch", after=start)

    class Dependency(Canary):
        @launch
        async def on_launch(self) -> None:
            log.append("dep.launch")

    class Root(Canary):
        dependency = dep(Dependency)

        @start
        async def s(self) -> None:
            log.append("root.start")

    root = Root()
    async with root:
        assert log == ["root.start"], "框架不会自己推进第四个阶段"
        await advance(root, launch)
    assert log == ["root.start", "dep.launch"]


async def test_concurrent_dependencies_advance_together():
    """互不依赖的依赖同时推进——0.9.x 要靠 ``start_concurrency=`` 配置，现在是默认。"""
    order: list[str] = []

    class Slow(Canary):
        @start
        async def s(self) -> None:
            order.append("slow.enter")
            await asyncio.sleep(0.02)
            order.append("slow.exit")

    class Quick(Canary):
        @start
        async def s(self) -> None:
            order.append("quick.enter")
            order.append("quick.exit")

    class Root(Canary):
        slow = dep(Slow)
        quick = dep(Quick)

    async with Root():
        pass
    # quick 在 slow 还没结束时就跑完了——两条分支是并发推进的
    assert order.index("quick.exit") < order.index("slow.exit")

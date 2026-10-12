"""框架边界：阶段、失败、回收、重启，一条一条钉住。

和 ``library`` / ``telemetry`` / ``relay`` 的同名文件一样：不测业务，只记录**框架当前的
行为**。标了 **【毛病】** 的那条是这个场景试出来的问题。
"""

from __future__ import annotations

import socket

import pytest
from canary_framework import (
    Canary,
    CircularDependencyError,
    LifecycleError,
    Phase,
    dep,
    deps_of,
    enter,
    init,
    leave,
    scope_of,
    start,
    stop,
)
from canary_framework.test import running, unit

from pipeline.gate import Gate
from pipeline.http import root as root_class
from pipeline.jobs import JobBook
from pipeline.ledger import Ledger
from pipeline.phases import serving
from pipeline.settings import PipelineSettings
from pipeline.testing import settings

# -- 自定义阶段：两个方向 --------------------------------------------------

#: 本文件自己的阶段对，和 ``pipeline.phases`` 同构，只是用来观察顺序。
mark = Phase("mark")
busy = Phase("busy", after=start, leave=mark)


class Low(Canary):
    """A dependency."""

    def __init__(self) -> None:
        self.order: list[str] = []

    @busy
    async def went_busy(self) -> None:
        ORDER.append("low:busy")

    @mark
    async def went_idle(self) -> None:
        ORDER.append("low:mark")


class High(Canary):
    """Its dependent."""

    low = dep(Low)

    @busy
    async def went_busy(self) -> None:
        ORDER.append("high:busy")

    @mark
    async def went_idle(self) -> None:
        ORDER.append("high:mark")


ORDER: list[str] = []


async def test_enter_is_dependencies_first_and_leave_is_dependents_first() -> None:
    """一个阶段的两个方向互为镜像——这就是两步停机能成立的全部原因。

    ``enter`` 依赖在前（"资源先就位"），``leave`` 本单元在前（"先停止接受"）。所以
    "关闸"必须写成一次 ``leave``：写成 ``enter`` 的话顺序会反过来，最该先关的接入口
    反而最后知道。
    """
    ORDER.clear()
    async with running(High) as high:
        await enter(high, busy)
        assert ORDER == ["low:busy", "high:busy"]

        await leave(high, busy)
        assert ORDER == ["low:busy", "high:busy", "high:mark", "low:mark"]


async def test_a_phase_runs_once_however_many_times_it_is_entered() -> None:
    ORDER.clear()
    async with running(High) as high:
        await enter(high, busy)
        await enter(high, busy)
        await enter(high, busy)
        assert ORDER == ["low:busy", "high:busy"]


async def test_a_phase_can_be_entered_again_after_it_was_left() -> None:
    """离开之后回到空闲，所以可以再进——``serving`` 在重启时就是这样又跑一遍的。"""
    ORDER.clear()
    async with running(High) as high:
        await enter(high, busy)
        await leave(high, busy)
        await enter(high, busy)
    assert ORDER == ["low:busy", "high:busy", "high:mark", "low:mark", "low:busy", "high:busy"]


async def test_entering_before_the_predecessor_is_refused() -> None:
    """``after=start`` 是一道栅栏：阶段不会被静默跳过。"""
    high = High()
    await high.init()
    with pytest.raises(LifecycleError, match="has not run"):
        await enter(high, busy)


async def test_a_phase_without_a_leave_cannot_be_left() -> None:
    lonely = Phase("lonely", after=start)
    async with running(High) as high:
        with pytest.raises(LifecycleError, match="declares no leave phase"):
            await leave(high, lonely)


async def test_leaving_serving_leaves_start_alone(pipe) -> None:
    """``start`` 是 ``serving`` 的**前驱**，不是后继，所以关闸之后整张图还是启动着的。"""
    await leave(pipe, serving)
    assert pipe.gate.accepting is False          # @quiesce 跑过了
    assert pipe.fast.tasks                        # 消费者还在
    assert pipe.fast.queue.closed is True         # 但不再接新活

    await pipe.stop()                             # @stop 照常跑
    assert pipe.fast.tasks == []


async def test_the_root_drives_the_extra_phases_through_start_and_stop(pipe) -> None:
    """覆盖 ``start()`` / ``stop()`` 是框架明确支持的写法，所以调用者不必记得多调一步。"""
    assert "serving: 接入开放" in pipe.journal.entries
    await pipe.stop()
    assert any(step.startswith("quiesce:") for step in pipe.journal.entries)


# -- 启动失败与停止失败 ----------------------------------------------------


async def test_a_failed_start_reclaims_what_had_started_and_skips_the_extra_phase() -> None:
    """端口被占用：``@start`` 抛 ``OSError``，已启动的单元照常回收，``serving`` 不会推进。

    顺序在这里很关键：两条通道是 ``IngestServer`` 的**依赖**（``StatusApi`` 读它们），
    所以它们先起来、然后服务器失败、然后它们被回收。``enter(serving)`` 写在
    ``super().start()`` 之后，所以它一次都没跑——日志里一条 ``serving:`` 都没有。
    """
    squatter = socket.create_server(("127.0.0.1", 0))
    try:
        taken = squatter.getsockname()[1]
        root = root_class("fastapi")()
        scope_of(root).provide(PipelineSettings, settings(port=taken))

        with pytest.raises(OSError):
            async with root:
                pass

        assert root.fast.tasks == []                       # 消费者被收掉了
        assert root.fast.queue.closed is True              # 队列被关掉了
        assert root.gate.accepting is False
        assert [step for step in root.journal.entries if step.startswith("stop:")]
        assert not [step for step in root.journal.entries if step.startswith("serving:")]
    finally:
        squatter.close()


async def test_a_failing_stop_hook_does_not_stop_the_others() -> None:
    order: list[str] = []

    class Leaf(Canary):
        @stop
        async def note(self) -> None:
            order.append("leaf")

    class Angry(Canary):
        leaf = dep(Leaf)

        @stop
        async def boom(self) -> None:
            order.append("angry")
            raise RuntimeError("stop 失败")

    class Root(Canary):
        angry = dep(Angry)

        @stop
        async def note(self) -> None:
            order.append("root")

    root = Root()
    await root.init()
    await root.start()
    with pytest.raises(ExceptionGroup) as caught:
        await root.stop()
    assert order == ["root", "angry", "leaf"]  # 失败的那个没有挡住它的依赖
    assert "stop 失败" in str(caught.value.exceptions[0])


async def test_a_cycle_is_reported_before_any_hook_runs() -> None:
    ran: list[str] = []

    class A(Canary):
        @init
        def note(self) -> None:
            ran.append("a")

    class B(Canary):
        a = dep(A)

        @init
        def note(self) -> None:
            ran.append("b")

    A.b = dep(B)  # 事后制造一个环
    try:
        with pytest.raises(CircularDependencyError):
            async with running(B):
                pass
        assert ran == []
    finally:
        del A.b


# -- 子类换掉一条依赖 ------------------------------------------------------


async def test_overriding_a_dep_by_name_replaces_the_base_class_edge() -> None:
    """子类用同名属性覆盖 ``dep()`` 就是替换——依赖和钩子一样按**属性名**解析。

    上一轮这里是一条【毛病】：依赖当时按**类型**收集，``vars(每个基类)`` 里的每个 ``Dep``
    都算一条边，于是"基类给个默认协作者、子类换掉它"这种最自然的模板写法会**静默多启动
    一个单元**（``Default`` 被构造、``@start``、``@stop`` 全跑一遍，只是没人用它）。

    现在基类那条边随覆盖消失，所以 ``pipeline/workers.py`` 与 ``shop/warehouse.py`` 都写回
    了最自然的样子：基类一条默认 ``dep()``，子类换掉它。
    """
    started_units: list[str] = []

    class Default(Canary):
        @start
        async def note(self) -> None:
            started_units.append("Default")

    class Replacement(Default):
        @start
        async def note(self) -> None:
            started_units.append("Replacement")

    class Base(Canary):
        collaborator = dep(Default)

    class Derived(Base):
        collaborator = dep(Replacement)

    assert [cls.__name__ for cls in deps_of(Base)] == ["Default"]
    assert [cls.__name__ for cls in deps_of(Derived)] == ["Replacement"]

    async with running(Derived) as derived:
        assert isinstance(derived.collaborator, Replacement)
        assert started_units == ["Replacement"], "基类那条边不该再成立"


async def test_overriding_a_dep_with_something_else_removes_it() -> None:
    """覆盖成不是 ``dep()`` 的东西，这条依赖就没有了——和"覆盖但不再标记的钩子"一个道理。"""

    class Leaf(Canary):
        pass

    class Base(Canary):
        leaf = dep(Leaf)

    class Plain(Base):
        leaf = "不再是依赖"  # type: ignore[assignment]

    assert [cls.__name__ for cls in deps_of(Base)] == ["Leaf"]
    assert deps_of(Plain) == ()

    async with running(Plain) as plain:
        assert plain.leaf == "不再是依赖"


async def test_the_two_lanes_each_replace_the_default_queue(pipe) -> None:
    """本场景的实际用法：``WorkerPool.queue = dep(JobQueue)`` 是默认，两条通道各换一个。"""
    from pipeline.lanes import BulkQueue, FastQueue
    from pipeline.queue import JobQueue
    from pipeline.workers import WorkerPool

    assert JobQueue in deps_of(WorkerPool)
    assert JobQueue not in deps_of(type(pipe.fast))
    assert isinstance(pipe.fast.queue, FastQueue)
    assert isinstance(pipe.bulk.queue, BulkQueue)
    # 图上没有那个默认队列的实例
    assert JobQueue not in scope_of(pipe).instances


# -- 测试辅助 --------------------------------------------------------------


async def test_unit_reaches_what_nobody_declared(pipe) -> None:
    """测试常常要够到一个自己没声明依赖的单元。"""
    assert unit(pipe, Ledger) is pipe.ledger
    assert unit(pipe, JobBook) is pipe.fast.book
    assert unit(pipe, Gate) is pipe.gate


async def test_unit_before_the_lifecycle_raises() -> None:
    with pytest.raises(LookupError):
        unit(root_class("fastapi")(), Ledger)


async def test_a_double_must_be_an_instance_of_what_it_replaces() -> None:
    with pytest.raises(TypeError):
        async with running(root_class("fastapi"), {PipelineSettings: object()}):  # type: ignore[dict-item]
            pass


async def test_dependencies_cannot_be_assigned(pipe) -> None:
    """替换依赖只能经 ``provide``：赋值只会改到一个属性，整张图不会生效。"""
    with pytest.raises(AttributeError, match="cannot be assigned"):
        pipe.ledger = Ledger()

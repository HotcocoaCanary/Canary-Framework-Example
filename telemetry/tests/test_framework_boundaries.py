"""Framework boundaries surfaced by the *daemon* shape — scenario 1 cannot reach these.

An HTTP app never sees most of this: uvicorn owns the lifecycle, a startup
failure just kills the process, and nothing runs between requests.  A
long-running daemon owns its own lifecycle, so the framework's lifecycle
semantics become load-bearing.

最终版（``release/0.9.3`` @ ``322315e``）把替换入口 ``provide=`` 整个删掉了：
图上的实例全部由框架无参构造。原来钉住 ``provide`` 语义的四条测试因此改成钉住
**它不在了**，以及在没有它之后测试还能怎么写。生命周期的四条修复（#012 / #014 /
回滚 / 幂等 stop）照旧从正面钉住。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from canary_framework import Canary, LifecycleState, cocoa, on_init, on_start, on_stop
from canary_framework.common.error import ConstructionError, LifecycleError

log: list[str] = []


@pytest.fixture(autouse=True)
def _clear_log():
    log.clear()
    yield


# --- #012：启动失败现在会回滚 --------------------------------------------


@cocoa
class Acquires:
    @on_start
    async def start(self) -> None:
        log.append("Acquires.start")

    @on_stop
    async def stop(self) -> None:
        log.append("Acquires.stop")


@cocoa(deps=[Acquires])
class HalfStarted:
    acquires: Acquires

    @on_start
    async def start(self) -> None:
        log.append("HalfStarted.start")
        raise RuntimeError("启动失败")

    @on_stop
    async def stop(self) -> None:
        # 失败单元自己也在台账上，所以这个钩子会跑——它必须容忍
        # 「@on_start 只跑了一半」的自己。
        log.append("HalfStarted.stop")


async def test_a_failed_start_releases_everything_it_had_acquired():
    """已启动的单元按逆序回收，**含失败单元自身**，原异常原样抛出。

    这条对本项目是硬需求：``SupervisedTasks`` / ``HttpSampleSource`` /
    ``WebhookAlertSink`` 都在 ``@on_start`` 里拿资源。0.9.2 里任何一个后启动的
    单元失败，它们的 ``@on_stop`` 永远不跑——任务继续跑、HTTP 连接不关。
    """
    app = Canary(HalfStarted)
    await app.init()
    with pytest.raises(RuntimeError, match="启动失败"):
        await app.start()

    assert log == [
        "Acquires.start",
        "HalfStarted.start",
        "HalfStarted.stop",  # 失败的那个先回收
        "Acquires.stop",
    ]
    assert app.state is LifecycleState.FAILED


async def test_stop_after_a_failed_start_is_legal_and_idempotent():
    """0.9.2 里 ``FAILED`` 拒绝 ``stop()``，连手动清理都不行。"""
    app = Canary(HalfStarted)
    await app.init()
    with pytest.raises(RuntimeError):
        await app.start()

    await app.stop()  # 不再抛 LifecycleError
    await app.stop()  # 幂等
    # 回收只做一次：台账已清空，不会重复执行 @on_stop
    assert log.count("Acquires.stop") == 1
    assert app.state is LifecycleState.FAILED


async def test_a_failure_during_rollback_rides_along_as_a_note():
    """回收自身失败不改变异常类型，也不吞掉原因——附成 note。"""

    @cocoa
    class BadCleanup:
        @on_stop
        async def stop(self) -> None:
            raise RuntimeError("回收也失败了")

    @cocoa(deps=[BadCleanup])
    class Fails:
        bad_cleanup: BadCleanup

        @on_start
        async def start(self) -> None:
            raise ValueError("原始失败")

    app = Canary(Fails)
    await app.init()
    with pytest.raises(ValueError, match="原始失败") as caught:
        await app.start()

    notes = getattr(caught.value, "__notes__", [])
    assert any("回收也失败了" in note for note in notes), notes


async def test_an_init_failure_leaves_nothing_to_reclaim():
    """``@on_init`` 阶段失败时还没有任何单元进过 ``@on_start``。"""

    @cocoa
    class BadInit:
        @on_init
        async def boom(self) -> None:
            raise RuntimeError("init 失败")

        @on_stop
        async def stop(self) -> None:
            log.append("BadInit.stop")

    app = Canary(BadInit)
    with pytest.raises(RuntimeError, match="init 失败"):
        await app.init()
    assert app.state is LifecycleState.FAILED
    await app.stop()
    assert log == []


# --- #014：一个停止钩子抛异常不再中断整轮关停 ---------------------------


@cocoa
class Innermost:
    @on_stop
    async def stop(self) -> None:
        log.append("Innermost.stop")


@cocoa(deps=[Innermost])
class BadStop:
    innermost: Innermost

    @on_stop
    async def stop(self) -> None:
        log.append("BadStop.stop")
        raise RuntimeError("关停失败")


@cocoa(deps=[BadStop])
class Outermost:
    bad_stop: BadStop

    @on_stop
    async def stop(self) -> None:
        log.append("Outermost.stop")


async def test_a_failing_stop_hook_no_longer_strands_the_ones_below_it():
    """最底层的连接池 / 后台任务照样被回收，异常合并成 ExceptionGroup。"""
    app = Canary(Outermost)
    await app.init()
    await app.start()

    with pytest.raises(ExceptionGroup) as caught:
        await app.stop()

    assert log == ["Outermost.stop", "BadStop.stop", "Innermost.stop"]
    assert [type(e) for e in caught.value.exceptions] == [RuntimeError]
    assert "关停失败" in str(caught.value.exceptions[0])
    # 异常带上了出处，否则 ExceptionGroup 里认不出是谁抛的
    assert any("BadStop" in n for n in getattr(caught.value.exceptions[0], "__notes__", []))
    assert app.state is LifecycleState.FAILED


async def test_stop_collects_every_failure_not_just_the_first():
    @cocoa
    class BadA:
        @on_stop
        async def stop(self) -> None:
            raise RuntimeError("A")

    @cocoa(deps=[BadA])
    class BadB:
        bad_a: BadA

        @on_stop
        async def stop(self) -> None:
            raise RuntimeError("B")

    app = Canary(BadB)
    await app.init()
    await app.start()
    with pytest.raises(ExceptionGroup) as caught:
        await app.stop()
    assert {str(e) for e in caught.value.exceptions} == {"A", "B"}


# --- 替换入口没有了：测试还能怎么写 ----------------------------------------


async def test_the_substitution_entry_is_gone():
    """``Canary(provide=...)`` 被删——``Canary`` 只收根。

    理由（提交信息里写得很清楚）：单元"从哪来"只该有一个答案，而 ``provide`` 与
    "必须能无参构造"这条规则一直在互咬（旧 #024）。代价是整图跑假实现的能力没有了。
    """

    @cocoa
    class Unit:
        pass

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        Canary(Unit, provide={Unit: object()})  # type: ignore[call-arg]


async def test_the_seam_that_replaced_it_is_setattr_between_init_and_start():
    """注入提前到 ``init()`` 之后，``init()`` 与 ``start()`` 之间就是替换窗口。

    本项目的整套管线测试靠这个窗口把 ``Clock`` 换成手动时钟
    （``telemetry/testing.py::swap_clock``）——一次 ``sleep`` 都不需要。
    但这条缝有两个框架不管的地方，都钉在下面。
    """

    @cocoa
    class RealSource:
        async def read(self) -> str:
            return "real"

    @cocoa(deps=[RealSource])
    class Consumer:
        real_source: RealSource

    class FakeSource:
        opened = False

        @on_start
        async def open(self) -> None:  # 不会被执行：它不在图上
            self.opened = True

        async def read(self) -> str:
            return "fake"

    fake = FakeSource()
    app = Canary(Consumer)
    await app.init()
    app[Consumer].real_source = fake  # type: ignore[assignment]
    await app.start()

    assert await app[Consumer].real_source.read() == "fake"
    # 1. 替身的生命周期钩子不跑——持有资源的替身要自己开关。
    assert not fake.opened
    # 2. 运行时不知道换过：canary[RealSource] 仍然是真的那个，真的那个也照常启动。
    assert app[RealSource] is not fake
    await app.stop()


async def test_the_real_unit_is_still_constructed_and_started():
    """替换发生在图建好之后，所以被替掉的那棵子树照样实例化、照样启动。

    ``provide`` 从前是在**建图**时就跳过它们的（"替掉数据库之后不该还去连数据库"）。
    现在做不到：真单元的 ``@on_start`` 会先跑一遍。对本项目无害（``Clock`` 很轻），
    但换成"真的会去连数据库的仓储"就不是无害的了。
    """

    started: list[str] = []

    @cocoa
    class Expensive:
        @on_start
        async def connect(self) -> None:
            started.append("Expensive")

    @cocoa(deps=[Expensive])
    class Repo:
        expensive: Expensive

    @cocoa(deps=[Repo])
    class Service:
        repo: Repo

    app = Canary(Service)
    await app.init()
    app[Service].repo = object()  # type: ignore[assignment]
    await app.start()

    assert Expensive in app.order
    assert started == ["Expensive"], "换掉仓储也拦不住它的依赖去连接"
    await app.stop()


async def test_dependencies_are_injected_before_on_init_runs():
    """注入提前到了 ``init()``：``@on_init`` 现在看得见自己的依赖。

    0.9.3 里注入发生在 ``start()``，``@on_init`` 读依赖必然 ``AttributeError``；
    文档（docs/zh/cocoa.md、dependency-injection.md）至今仍写着 start 阶段注入。
    """

    @cocoa
    class Dep:
        value = 7

    seen: list[int] = []

    @cocoa(deps=[Dep])
    class Uses:
        dep: Dep

        @on_init
        def read(self) -> None:
            seen.append(self.dep.value)

    await Canary(Uses).init()
    assert seen == [7]


# --- STILL BROKEN --------------------------------------------------------


async def test_stop_before_start_reports_success_instead_of_refusing():
    """``stop()`` 在 NEW / INITIALIZED 上静默成功，文档说它该抛 LifecycleError。

    守护进程的形态下这条最刺眼：``init()`` 跑过 ``@on_init``（本项目在那里建
    调度器作业表），随后 ``stop()`` 报告 STOPPED，却一个 ``@on_stop`` 都不跑。
    "已停止"因此不再等于"已回收"——运维看状态机做决定时会被误导。
    见 doc/bug/023-stop-before-start-reports-stopped-without-reclaiming.md
    """

    @cocoa
    class Unit:
        @on_init
        def prepare(self) -> None:
            log.append("Unit.init")

        @on_stop
        async def release(self) -> None:
            log.append("Unit.stop")

    fresh = Canary(Unit)
    await fresh.stop()
    assert fresh.state is LifecycleState.STOPPED, "文档承诺的是 LifecycleError"

    inited = Canary(Unit)
    await inited.init()
    await inited.stop()
    assert inited.state is LifecycleState.STOPPED
    assert log == ["Unit.init"], "报告 STOPPED，但 @on_init 拿到的东西没人回收"


async def test_a_unit_that_needs_constructor_arguments_is_told_where_to_put_them():
    """旧 #024 的解法：删掉另一条路，错误信息因此只说得出一条出路。

    从前 ``ConstructionError`` 指向 ``provide=``、而 ``provide=`` 又拒收任何声明了
    ``deps`` 的实例，两条建议互相排斥。现在只剩"把构造参数变成依赖，值从协作者那里读，
    读取动作放进 ``@on_init`` / ``@on_start``"——本项目的 ``Database``、
    ``EmbeddingModel``、``SampleSource`` 全是这个形状。
    """

    @cocoa
    class Settings:
        dsn = "postgres://x"

    @cocoa(deps=[Settings])
    class Engine:
        settings: Settings

        def __init__(self, pool_size: int) -> None:
            self.pool_size = pool_size

    @cocoa(deps=[Engine])
    class Service:
        engine: Engine

    with pytest.raises(ConstructionError) as caught:
        await Canary(Service).init()
    message = str(caught.value)
    assert "provide" not in message, "另一条路已经不存在，就不该再出现在建议里"
    assert "@on_init" in message or "@on_start" in message


async def test_the_slow_callback_probe_now_covers_the_startup_step(caplog):
    """#025 修好了：探针打开后让出一次，启动期的阻塞终于抓得到。

    原因很具体——asyncio 在回调**开始执行之前**就读了 ``loop._debug``，而探针是在
    ``init()`` 里、也就是那个回调执行到一半时才打开的。常规守护进程写法
    （``asyncio.run(main())`` + ``async with Canary(...)``，中间没有真正的让出）
    因此整段启动都测不到——本项目的 ``main.py`` 正是这个形状。
    """
    import os
    import time

    @cocoa
    class BlockingStart:
        @on_start
        async def stall(self) -> None:
            time.sleep(0.2)

    async def whole_startup_in_one_step() -> None:
        async with Canary(BlockingStart):
            pass

    os.environ["CANARY_SLOW_CALLBACK_SECONDS"] = "0.05"
    try:
        # 独立的 task：慢回调的 WARNING 是在一个 step **结束之后**才写的。
        with caplog.at_level(logging.WARNING, logger="asyncio"):
            await asyncio.create_task(whole_startup_in_one_step())
    finally:
        del os.environ["CANARY_SLOW_CALLBACK_SECONDS"]

    assert [r for r in caplog.records if "took" in r.getMessage()], "启动期的阻塞应当被抓到"


async def test_no_scheduling_or_task_facility_still():
    """本项目仍然要自带 ``SupervisedTasks`` 与 ``Scheduler``。

    0.9.3 给了 web 侧的 ``BackgroundTask``（挂在响应上），但那是 Starlette 的，
    且只在请求路径上；纯 core 的守护进程形态依然什么都没有。
    见 doc/bug/010-no-background-tasks.md
    """
    public = {name for name in vars(Canary) if not name.startswith("_")}
    assert public == {"state", "order", "instances", "init", "start", "stop"}
    assert not any(k in name for name in public for k in ("task", "sched", "timer", "job"))


async def test_multi_root_still_has_no_after_all_position():
    """多根编排时没有单元最后启动——0.9.3 明确了这一点，但没有补钩子。

    本项目因此保持单根：``TelemetryDaemon.launch`` 就是 after-all。
    见 doc/bug/013-startup-order-guarantees-undocumented.md
    """

    @cocoa
    class Shared:
        pass

    @cocoa(deps=[Shared])
    class RootA:
        shared: Shared

    @cocoa(deps=[Shared])
    class RootB:
        shared: Shared

    app = Canary(RootA, RootB)
    await app.init()
    await app.start()
    assert app[RootA].shared is app[RootB].shared
    assert app.order[0] is Shared
    assert app.order[-1] in (RootA, RootB)  # 谁最后是排序的偶然，不是承诺
    await app.stop()


# --- 框架做对的部分（回归保护） -------------------------------------------


async def test_async_context_manager_drives_init_start_stop():
    app = Canary(Innermost)
    async with app as started:
        assert started.state is LifecycleState.STARTED
    assert app.state is LifecycleState.STOPPED
    assert log == ["Innermost.stop"]


async def test_a_transient_state_still_refuses_stop():
    """并发误用仍然要响——幂等只对终态成立。"""
    app = Canary(Innermost)
    await app.init()
    app._state = LifecycleState.STARTING  # 模拟并发调用者看到的中间态
    with pytest.raises(LifecycleError, match="illegal transition|illegal while"):
        await app.stop()


async def test_the_assembly_summary_names_order_and_deps(caplog):
    """``canary.runtime`` 开到 DEBUG 时，装配结果一次性说清楚。"""

    @cocoa
    class Dep:
        pass

    @cocoa(deps=[Dep])
    class App:
        dep: Dep

    with caplog.at_level(logging.DEBUG, logger="canary.runtime"):
        app = Canary(App)
        await app.init()
        await app.start()
        await app.stop()

    summary = "\n".join(r.getMessage() for r in caplog.records)
    assert "start order" in summary
    assert "Dep" in summary
    assert "App" in summary

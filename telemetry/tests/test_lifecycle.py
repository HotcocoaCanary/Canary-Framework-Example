"""Lifecycle — what 0.10.0 guarantees for a long-running, non-ASGI process.

场景一从不碰这些：那里 FastAPI 的 lifespan 驱动 init/start/stop，启动失败直接打死进程。
守护进程自己拥有生命周期，框架的生命周期语义因此变成承重墙。
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest
from canary_framework import Canary, LifecycleError, dep, scope_of, start

from telemetry.daemon import AlertDaemon, CollectorDaemon, TelemetryDaemon
from telemetry.infra.clock import Clock
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.phases import launch
from telemetry.settings import AppConfig
from telemetry.store.metric_store import MetricStore
from telemetry.testing import unit


def test_the_daemon_never_imports_a_web_framework():
    """场景二只依赖核心——而 0.10.0 的核心零第三方依赖。

    0.9.x 时这条断言盯的是"web 扩展是否被惰性 import"。0.10.0 把
    ``canary_framework.web`` 整个删了，所以现在它盯的是另一件事：纯核心编排跑完
    一整个生命周期，进程里不该出现任何 web 栈。

    跑在**子进程**里：这个断言是关于整个进程的。
    """
    script = textwrap.dedent(
        """
        import asyncio, json, sys
        from telemetry.daemon import TelemetryDaemon

        async def main():
            async with TelemetryDaemon():
                pass

        asyncio.run(main())
        print(json.dumps(sorted(
            m for m in sys.modules
            if m.split(".")[0] in {"starlette", "fastapi", "uvicorn"}
        )))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


async def test_canary_core_has_no_third_party_dependency():
    """``import canary_framework`` 之后不该多出任何第三方包。"""
    script = textwrap.dedent(
        """
        import json, sys
        before = set(sys.modules)
        import canary_framework
        added = {m.split(".")[0] for m in set(sys.modules) - before}
        third_party = added - sys.stdlib_module_names - {"canary_framework"}
        print(json.dumps(sorted(m for m in third_party if not m.startswith("_"))))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


async def test_dependencies_start_before_dependents():
    """推进沿依赖向下：依赖的 ``@start`` 一定早于依赖者的。"""
    order: list[str] = []

    class Inner(Canary):
        @start
        async def go(self) -> None:
            order.append("inner")

    class Outer(Canary):
        inner = dep(Inner)

        @start
        async def go(self) -> None:
            order.append("outer")

    async with Outer():
        pass
    assert order == ["inner", "outer"]


async def test_units_reached_from_two_branches_are_one_instance():
    """一个作用域内每个类型只有一个实例。"""
    async with TelemetryDaemon() as daemon:
        assert daemon.collector.scheduler is daemon.alerts.scheduler
        assert unit(daemon, MetricStore) is daemon.collector.store
        assert unit(daemon, AppConfig) is daemon.collector.config
        assert daemon.alerts.dispatcher.clock is unit(daemon, Clock)


async def test_async_with_drives_the_whole_lifecycle():
    """没有 ASGI 服务器参与——守护进程自己走完一生。

    0.10.0 里没有运行时容器了：根单元自己就是入口。
    """
    daemon = TelemetryDaemon()
    async with daemon as started_daemon:
        assert started_daemon is daemon
        assert unit(daemon, SupervisedTasks).running >= 1
    assert unit(daemon, SupervisedTasks).running == 0


async def test_stop_cancels_and_awaits_every_background_task():
    """No orphaned tasks survive shutdown — ``SupervisedTasks`` 加的那条保证。"""
    daemon = TelemetryDaemon()
    await daemon.init()
    await daemon.start()
    tasks = unit(daemon, SupervisedTasks)
    assert tasks.running == 2  # collect + evaluate
    await daemon.stop()
    assert tasks.running == 0
    assert tasks.failures == []


# --- 第四个阶段 ---------------------------------------------------------


async def test_launch_runs_after_every_start():
    """``@launch`` 是"全图起来之后"的位置——0.9.x 只能靠拓扑巧合去凑。"""
    order: list[str] = []

    class Dependency(Canary):
        @start
        async def s(self) -> None:
            order.append("dep.start")

        @launch
        async def on_launch(self) -> None:
            order.append("dep.launch")

    class Root(Canary):
        dependency = dep(Dependency)

        @start
        async def s(self) -> None:
            order.append("root.start")

        @launch
        async def on_launch(self) -> None:
            order.append("root.launch")

        async def start(self) -> None:
            await super().start()
            from canary_framework import advance

            await advance(self, launch)

    async with Root():
        pass
    # 关键：两个 @start 都跑完，才轮到任何一个 @launch
    assert order == ["dep.start", "root.start", "dep.launch", "root.launch"]


async def test_the_scheduler_only_spawns_loops_in_launch():
    """注册在 ``@start``，开跑在 ``@launch``——中间那道栅栏是这条测试的全部内容。"""
    daemon = TelemetryDaemon()
    await daemon.init()

    scheduler = unit(daemon, Scheduler)
    assert scheduler.jobs == {}, "init 之后还不该有作业"

    await daemon.start()
    assert set(scheduler.jobs) == {"collect", "evaluate"}
    assert scheduler.started, "@launch 应当已经把循环开起来了"
    await daemon.stop()


async def test_a_phase_with_an_unmet_predecessor_refuses_to_run():
    """``after=start`` 是栅栏，不是注释：跳过 ``start()`` 直接推 ``launch`` 会抛错。"""
    from canary_framework import advance

    class Unit(Canary):
        @launch
        async def on_launch(self) -> None: ...

    unit_ = Unit()
    await unit_.init()
    with pytest.raises(LifecycleError, match="@start"):
        await advance(unit_, launch)


async def test_start_before_init_is_refused():
    """``start`` 声明了 ``after=init``，所以漏掉 ``init()`` 会响，而不是静默跳过。"""
    daemon = TelemetryDaemon()
    with pytest.raises(LifecycleError, match="@init"):
        await daemon.start()


# --- 作业注册 -----------------------------------------------------------


async def test_jobs_cannot_be_registered_once_the_loops_are_running():
    """Registration closes at launch — a job added later would never be spawned."""
    daemon = TelemetryDaemon()
    await daemon.init()
    await daemon.start()
    with pytest.raises(RuntimeError, match="调度器已启动"):
        unit(daemon, Scheduler).every("late", 1.0, daemon.collector.collect_once)
    await daemon.stop()


async def test_duplicate_job_names_are_rejected():
    """Two units claiming one job name would silently shadow each other."""

    async def noop() -> None:
        return None

    scheduler = Scheduler()
    scheduler.every("collect", 1.0, noop)
    with pytest.raises(ValueError, match="重复的作业名"):
        scheduler.every("collect", 1.0, noop)


async def test_each_root_is_its_own_graph():
    """两个各自构造的根是两张互不相干的图——作用域即是图。"""
    a, b = TelemetryDaemon(), TelemetryDaemon()
    await a.init()
    await b.init()
    assert scope_of(a) is not scope_of(b)
    assert unit(a, MetricStore) is not unit(b, MetricStore)


async def test_collector_and_alert_daemons_share_the_scheduler():
    async with TelemetryDaemon() as daemon:
        assert unit(daemon, CollectorDaemon).scheduler is unit(daemon, AlertDaemon).scheduler

"""End-to-end — the scheduler actually driving the pipeline on a real clock.

这套件里别处都是手动推进时间。这几条让真循环跑上零点几秒，因为一个"只有测试手动调用
才工作"的调度器算不上调度器。
"""

from __future__ import annotations

import asyncio

from canary_framework import scope_of

from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import Clock
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.settings import AppConfig
from telemetry.testing import seed, unit


async def _fast_daemon() -> TelemetryDaemon:
    """A daemon on a *real* clock but very short intervals.

    注意时钟：这几条要让调度器自己的循环跑起来，所以时间必须真的流逝——这里**不换**
    时钟，只把间隔调小。配置照旧走预登记，因为作业注册发生在 ``@start``，
    那时配置必须已经是最终值。
    """
    daemon = TelemetryDaemon()
    seed(
        scope_of(daemon),
        AppConfig,
        AppConfig(collect_interval_seconds=0.01, evaluate_interval_seconds=0.02),
    )
    await daemon.init()
    await daemon.start()
    return daemon


async def test_the_loops_run_without_anyone_calling_them():
    daemon = await _fast_daemon()
    await asyncio.sleep(0.15)
    status = daemon.status()
    await daemon.stop()

    assert status["jobs"]["collect"]["ticks"] > 0
    assert status["jobs"]["evaluate"]["ticks"] > 0
    assert status["collected_samples"] > 0
    assert status["task_failures"] == []


async def test_a_failing_tick_does_not_kill_its_job():
    """One bad poll must not silently end collection for the rest of the process."""
    daemon = await _fast_daemon()
    source = daemon.collector.source
    calls = {"n": 0}
    original = source.read

    async def flaky():
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("采集源瞬时故障")
        return await original()

    source.read = flaky
    await asyncio.sleep(0.15)
    stats = unit(daemon, Scheduler).jobs["collect"]
    await daemon.stop()

    assert stats.failures > 0, "应记录到失败的 tick"
    assert stats.ticks > 0, "失败之后作业仍在继续"
    assert "采集源瞬时故障" in (stats.last_error or "")


async def test_shutdown_leaves_no_running_tasks():
    daemon = await _fast_daemon()
    await asyncio.sleep(0.05)
    tasks = unit(daemon, SupervisedTasks)
    assert tasks.running == 2
    await daemon.stop()
    assert tasks.running == 0


async def test_status_snapshot_is_operator_readable():
    daemon = await _fast_daemon()
    await asyncio.sleep(0.05)
    status = daemon.status()
    await daemon.stop()

    assert set(status) == {
        "jobs",
        "running_tasks",
        "task_failures",
        "collected_samples",
        "evaluations",
        "alerts",
    }
    assert set(status["jobs"]) == {"collect", "evaluate"}
    assert set(status["alerts"]) == {"delivered", "suppressed"}


async def test_a_real_clock_is_used_when_nothing_is_seeded():
    """没有预登记时，``dep(Clock)`` 照常无参构造真时钟。"""
    daemon = await _fast_daemon()
    assert type(unit(daemon, Clock)) is Clock
    await daemon.stop()

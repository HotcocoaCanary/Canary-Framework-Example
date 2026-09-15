"""End-to-end — the scheduler actually driving the pipeline on a real clock.

Everything else in this suite advances time by hand.  These few tests let the
real loops run for a fraction of a second, because a scheduler that only works
when a test calls it manually is not a scheduler.
"""

from __future__ import annotations

import asyncio

from canary_framework import Canary
from telemetry.daemon import TelemetryDaemon
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.testing import apply_settings


async def _fast_daemon() -> Canary:
    """A daemon on a *real* clock but very short intervals.

    Note the clock: these tests let the scheduler's own loops run, so they need
    time to actually pass —— 所以这里**不换**时钟，只改间隔。
    改的是 ``init()`` 之后图上那一份共享 ``AppConfig``：作业注册发生在 ``@on_start``，
    此刻还没跑，改完再 ``start()`` 就能被读到。
    """
    app = Canary(TelemetryDaemon)
    await app.init()
    apply_settings(app, collect_interval_seconds=0.01, evaluate_interval_seconds=0.02)
    await app.start()
    return app


async def test_the_loops_run_without_anyone_calling_them():
    app = await _fast_daemon()
    await asyncio.sleep(0.15)
    status = app[TelemetryDaemon].status()
    await app.stop()

    assert status["jobs"]["collect"]["ticks"] > 0
    assert status["jobs"]["evaluate"]["ticks"] > 0
    assert status["collected_samples"] > 0
    assert status["task_failures"] == []


async def test_a_failing_tick_does_not_kill_its_job():
    """One bad poll must not silently end collection for the rest of the process."""
    app = await _fast_daemon()
    source = app[TelemetryDaemon].collector_daemon.sample_source
    calls = {"n": 0}
    original = source.read

    async def flaky():
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("采集源瞬时故障")
        return await original()

    source.read = flaky
    await asyncio.sleep(0.15)
    stats = app[Scheduler].jobs["collect"]
    await app.stop()

    assert stats.failures > 0, "应记录到失败的 tick"
    assert stats.ticks > 0, "失败之后作业仍在继续"
    assert "采集源瞬时故障" in (stats.last_error or "")


async def test_shutdown_leaves_no_running_tasks():
    app = await _fast_daemon()
    await asyncio.sleep(0.05)
    tasks: SupervisedTasks = app[SupervisedTasks]
    assert tasks.running == 2
    await app.stop()
    assert tasks.running == 0


async def test_status_snapshot_is_operator_readable():
    app = await _fast_daemon()
    await asyncio.sleep(0.05)
    status = app[TelemetryDaemon].status()
    await app.stop()

    assert set(status) == {
        "jobs", "running_tasks", "task_failures",
        "collected_samples", "evaluations", "alerts",
    }
    assert set(status["jobs"]) == {"collect", "evaluate"}
    assert set(status["alerts"]) == {"delivered", "suppressed"}

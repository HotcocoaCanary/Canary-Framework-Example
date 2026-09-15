"""Lifecycle — what Canary guarantees for a long-running, non-ASGI process.

Scenario 1 never exercised any of this: there, uvicorn's lifespan drove
``init``/``start``/``stop`` and a startup failure just killed the process.
A daemon has to own its own lifecycle, which puts weight on parts of the
framework an HTTP app never touches.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from canary_framework import Canary, LifecycleState
from telemetry.daemon import AlertDaemon, CollectorDaemon, TelemetryDaemon
from telemetry.infra.clock import Clock
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.settings import AppConfig
from telemetry.store.metric_store import MetricStore


def test_pure_cocoa_never_imports_the_web_extension():
    """The framework promises a lazy web import — this project banks on it.

    ``canary-telemetry`` deliberately does not depend on ``canary-framework[web]``.
    If the runtime imported it eagerly, this project would not install at all.

    Runs in a **subprocess** on purpose: the claim is about a whole process, and
    the sibling scenario in this workspace does import starlette, so an in-process
    assertion would only be measuring test ordering.
    """
    script = textwrap.dedent(
        """
        import asyncio, json, sys
        from canary_framework import Canary
        from telemetry.daemon import TelemetryDaemon

        async def main():
            async with Canary(TelemetryDaemon):
                pass

        asyncio.run(main())
        print(json.dumps(sorted(
            m for m in sys.modules
            if m.startswith("canary_framework.web") or m.split(".")[0] == "starlette"
        )))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


async def test_dependencies_start_before_dependents(runtime: Canary):
    await runtime.init()
    order = list(runtime.order)
    # 配置回到图上：beta 删掉了类级注解注入，AppConfig 又是一个普通节点，
    # 因而参与排序，并且排在所有读它的单元之前。
    assert order.index(AppConfig) < order.index(MetricStore)
    assert order.index(Clock) < order.index(Scheduler)
    assert order.index(CollectorDaemon) < order.index(TelemetryDaemon)
    assert order.index(AlertDaemon) < order.index(TelemetryDaemon)


async def test_the_single_root_starts_last(runtime: Canary):
    """The property ``Scheduler.start_all`` relies on.

    Kahn's algorithm emits a node only after every dependency, so the root —
    which transitively depends on the whole graph — is always last.  Reliable,
    but undocumented; see doc/bug/013.
    """
    await runtime.init()
    assert runtime.order[-1] is TelemetryDaemon


async def test_units_reached_from_two_branches_are_one_instance(runtime: Canary):
    await runtime.init()
    await runtime.start()
    collector = runtime[CollectorDaemon]
    alerts = runtime[AlertDaemon]
    assert collector.scheduler is alerts.scheduler
    assert runtime[MetricStore] is collector.metric_store
    await runtime.stop()


async def test_async_with_drives_the_whole_lifecycle():
    """No ASGI server involved — the daemon owns its own lifecycle."""
    app = Canary(TelemetryDaemon)
    async with app as started:
        assert started.state is LifecycleState.STARTED
        assert started[TelemetryDaemon].supervised_tasks.running >= 1
    assert app.state is LifecycleState.STOPPED


async def test_stop_cancels_and_awaits_every_background_task():
    """No orphaned tasks survive shutdown — the guarantee ``SupervisedTasks`` adds."""
    app = Canary(TelemetryDaemon)
    await app.init()
    await app.start()
    tasks = app[SupervisedTasks]
    assert tasks.running == 2  # collect + evaluate
    await app.stop()
    assert tasks.running == 0
    assert tasks.failures == []


async def test_the_scheduler_registers_both_jobs(runtime: Canary):
    await runtime.init()
    await runtime.start()
    jobs = runtime[Scheduler].jobs
    assert set(jobs) == {"collect", "evaluate"}
    # 配置回到图上之后，运行时直接给得出它——#017 随类级注解注入一起消失了。
    effective = runtime[AppConfig]
    assert effective is runtime[CollectorDaemon].app_config
    assert jobs["collect"].interval == effective.collect_interval_seconds
    await runtime.stop()


async def test_jobs_cannot_be_registered_once_the_loops_are_running(runtime: Canary):
    """Registration closes at launch — a job added later would never be spawned."""
    await runtime.init()
    await runtime.start()
    with pytest.raises(RuntimeError, match="调度器已启动"):
        runtime[Scheduler].every("late", 1.0, runtime[CollectorDaemon].collect_once)
    await runtime.stop()


async def test_duplicate_job_names_are_rejected():
    """Two units claiming one job name would silently shadow each other."""

    async def noop() -> None:
        return None

    scheduler = Scheduler()
    scheduler.every("collect", 1.0, noop)
    with pytest.raises(ValueError, match="重复的作业名"):
        scheduler.every("collect", 1.0, noop)

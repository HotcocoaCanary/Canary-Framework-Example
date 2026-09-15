"""Periodic job driver — the other piece Canary does not provide.

A daemon is *time*-driven, not request-driven, so something has to fire work on
an interval.  Canary has no scheduler, no timer and no cron hook
(``dir(Canary)`` is ``init/start/stop/state/order/instances``), so this unit
supplies one:

* drift-corrected sleeping — a job that takes 300ms on a 1s interval still fires
  at 1s, not 1.3s;
* a failing tick is logged and the loop continues, instead of killing the job;
* every loop runs under :class:`SupervisedTasks`, so shutdown is deterministic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from telemetry.infra.clock import Clock
from telemetry.infra.tasks import SupervisedTasks
from canary_framework import cocoa

logger = logging.getLogger("telemetry.scheduler")

Job = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class JobStats:
    name: str
    interval: float
    ticks: int = 0
    failures: int = 0
    last_error: str | None = field(default=None)


@cocoa(deps=[Clock, SupervisedTasks])
class Scheduler:
    clock: Clock
    supervised_tasks: SupervisedTasks

    _jobs: dict[str, JobStats]
    _pending: dict[str, Job]
    _started: bool

    def __init__(self) -> None:
        self._jobs = {}
        self._pending = {}
        self._started = False

    def every(self, name: str, interval_seconds: float, job: Job) -> None:
        """Register *job* to run every *interval_seconds*.

        Registration is separate from launching: units register in their own
        ``@on_start``, and the scheduler launches everything once the whole graph
        is up.  Without that split, a job could fire against a dependency whose
        ``@on_start`` has not run yet — the framework guarantees topological
        order, but a job started inside ``@on_start`` escapes that guarantee.
        """
        if self._started:
            raise RuntimeError(f"调度器已启动，无法再注册作业 {name}")
        if name in self._jobs:
            raise ValueError(f"重复的作业名: {name}")
        self._jobs[name] = JobStats(name=name, interval=interval_seconds)
        self._pending[name] = job

    def start_all(self) -> None:
        """Spawn one supervised loop per registered job.

        Deliberately **not** the scheduler's own ``@on_start``: hooks run in
        topological order, so a dependency starts *before* its dependents — the
        scheduler's hook would fire before any unit had registered a job.

        The composition root calls this instead.  That works because Kahn's
        algorithm emits a node only after all of its dependencies, so the single
        root — which transitively depends on everything — is always last
        (verified in ``tests/test_lifecycle.py``).  It is a reliable property,
        just an undocumented one; see ``doc/bug/013-startup-order-guarantees-undocumented.md``.
        """
        if self._started:
            return
        self._started = True
        for name, stats in self._jobs.items():
            self.supervised_tasks.spawn(f"job:{name}", self._run(name, stats))

    @property
    def jobs(self) -> dict[str, JobStats]:
        return dict(self._jobs)

    async def _run(self, name: str, stats: JobStats) -> None:
        job = self._pending[name]
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            next_at += stats.interval
            await asyncio.sleep(max(next_at - loop.time(), 0))  # 漂移校正
            try:
                await job()
                stats.ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 单次 tick 失败不应终止整个作业
                stats.failures += 1
                stats.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("作业 %s 第 %d 次执行失败", name, stats.ticks + stats.failures)

"""Periodic job driver — and the clearest place 0.10.0's phases pay off.

A daemon is *time*-driven, so something has to fire work on an interval. The
framework still supplies no scheduler, timer or cron hook — this unit does:

* drift-corrected sleeping —— 一个在 1 秒间隔上耗时 300ms 的作业仍然按 1 秒触发，
  而不是 1.3 秒；
* 单次 tick 失败只记账并继续，不会打死整个作业；
* 每个循环都跑在 :class:`SupervisedTasks` 下，因此关停是确定的。

**注册与开跑是两件事，分在两个阶段。** 各单元在自己的 ``@start`` 里注册作业，调度器
在 ``@launch`` 里统一开循环。必须分开的原因：推进沿依赖向下，依赖的 ``@start`` 早于
依赖者，而调度器是被依赖的那一方——它的 ``@start`` 跑的时候还没有任何单元注册过作业。

0.9.x 没有第四个阶段，这件事只能靠"根单元排在拓扑序最后"这条未写进文档的性质来绕
（旧 doc/bug/013）。0.10.0 里 ``Phase("launch", after=start)`` 就是答案，而且
``after=start`` 还顺带保证：``@launch`` 跑之前该单元的 ``@start`` 一定完成了。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from canary_framework import Canary, dep

from telemetry.infra.tasks import SupervisedTasks
from telemetry.phases import launch

logger = logging.getLogger("telemetry.scheduler")

Job = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class JobStats:
    name: str
    interval: float
    ticks: int = 0
    failures: int = 0
    last_error: str | None = field(default=None)


class Scheduler(Canary):
    tasks = dep(SupervisedTasks)

    def __init__(self) -> None:
        self._jobs: dict[str, JobStats] = {}
        self._pending: dict[str, Job] = {}
        self._started = False

    def every(self, name: str, interval_seconds: float, job: Job) -> None:
        """Register *job* to run every *interval_seconds*.

        注册在 ``@start`` 阶段进行，开跑在 ``@launch``——见模块开头。
        """
        if self._started:
            raise RuntimeError(f"调度器已启动，无法再注册作业 {name}")
        if name in self._jobs:
            raise ValueError(f"重复的作业名: {name}")
        self._jobs[name] = JobStats(name=name, interval=interval_seconds)
        self._pending[name] = job

    @launch
    async def start_all(self) -> None:
        """Spawn one supervised loop per registered job.

        挂在 ``@launch`` 上：这个阶段在全图的 ``@start`` 都完成之后才推进，所以此刻
        每个单元都已经注册过自己的作业了。
        """
        if self._started:
            return
        self._started = True
        for name, stats in self._jobs.items():
            self.tasks.spawn(f"job:{name}", self._run(name, stats))
        logger.info("调度器已启动，作业: %s", ", ".join(self._jobs) or "（无）")

    @property
    def jobs(self) -> dict[str, JobStats]:
        return dict(self._jobs)

    @property
    def started(self) -> bool:
        return self._started

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

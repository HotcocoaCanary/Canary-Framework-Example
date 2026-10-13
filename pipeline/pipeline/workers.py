"""The consumer pool —— the base class; one subclass per lane.

消费者池。HTTP 接入与队列消费在同一个进程里，而消费者这一侧是**一个最普通的单元**：
``@start`` 起任务、``@quiesce`` 排空、``@stop`` 收任务。没有专门的"后台任务"机制。

**基类给一条默认依赖，子类换掉它。** ``WorkerPool.queue = dep(JobQueue)`` 是默认，
``FastLane.queue = dep(FastQueue)`` 替换它——依赖和钩子一样按**属性名**解析，所以基类那条
边不再成立：``JobQueue`` 不会被构造，也不会被启动。

上一轮这里不是这样写的：当时依赖按**类型**收集，基类那条边会一起成立，``JobQueue`` 被白
构造、白启动一份（见 README 的"试出来的毛病"，现已修）。那时的绕法是基类只留一个类型
注解。
"""

from __future__ import annotations

import asyncio
import logging

from canary_framework import Canary, dep, start, stop

from pipeline.jobs import ABANDONED, FAILED, QUEUED, RUNNING, Job, JobBook
from pipeline.journal import Journal
from pipeline.ledger import AccountFrozen
from pipeline.phases import quiesce, serving
from pipeline.processor import Processor
from pipeline.queue import JobQueue, QueueClosed, QueueFull
from pipeline.settings import PipelineSettings

logger = logging.getLogger("pipeline.workers")


class WorkerPool(Canary):
    """A set of consumers on one queue.

    一条通道上的若干消费者。
    """

    config = dep(PipelineSettings)
    processor = dep(Processor)
    book = dep(JobBook)
    journal = dep(Journal)

    #: 这条通道的队列。子类用 ``dep(...)`` 覆盖它，基类这条边随之消失。
    queue = dep(JobQueue)
    #: 通道名，决定它从配置里读几个消费者。
    lane: str = "default"

    tasks: list[asyncio.Task[None]]
    #: 消费者名 → 它手上那个任务的 id。
    in_flight: dict[str, str]
    #: 上一次停机是否在预算内排空。
    drained: bool = False
    done: int = 0

    @property
    def size(self) -> int:
        return self.config.lane_workers.get(self.lane, 1)

    @start
    async def open(self) -> None:
        self.in_flight = {}
        self.drained = False
        self.tasks = [
            asyncio.create_task(self._consume(f"{self.lane}-{index}"), name=f"pipeline.{self.lane}.{index}")
            for index in range(self.size)
        ]

    @serving
    async def announce(self) -> None:
        self.journal.note(f"serving: {self.lane} 通道 {self.size} 个消费者开始接活")

    @quiesce
    async def drain(self) -> None:
        """Finish what is in flight, within the budget.

        停机第二步：把在途的做完。关闸是根单元在上一步做的，所以这里不会再有新活进来。
        """
        self.drained = await self.wait_idle(self.config.drain_timeout_seconds)
        left = self.queue.depth + len(self.in_flight)
        self.journal.note(
            f"quiesce: {self.lane} 通道排空{'完成' if self.drained else '超时'}，剩 {left} 个"
        )

    @stop
    async def close(self) -> None:
        tasks, self.tasks = getattr(self, "tasks", []), []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.journal.note(f"stop: {self.lane} 通道收工，完成 {self.done} 个")

    async def wait_idle(self, timeout: float) -> bool:
        """Wait until the queue is empty and nobody is busy, or until *timeout*.

        等到队列空、也没人手上有活；超时返回 ``False``。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.queue.depth or self.in_flight:
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.005)
        return True

    async def _consume(self, name: str) -> None:
        while True:
            job = await self.queue.take()
            self.in_flight[name] = job.job_id
            job.state = RUNNING
            try:
                await self.processor.run(job)
                self.done += 1
            except asyncio.CancelledError:
                # 停机预算用完了，这一批没做完：说清楚它的下场，再把取消传出去。
                job.state = ABANDONED
                job.error = "停机时在途，预算用完被放弃"
                raise
            except AccountFrozen as exc:
                self._requeue(job, f"账户冻结: {exc}")
            except Exception as exc:  # noqa: BLE001 - 一批失败不该带走消费者
                job.state = FAILED
                job.error = repr(exc)
                logger.exception("任务 %s 失败", job.job_id)
            finally:
                self.in_flight.pop(name, None)

    def _requeue(self, job: Job, reason: str) -> None:
        """Put a retryable failure back, unless it is out of attempts or the intake is closed.

        可重试的失败重投；次数用完、或者闸门已关，就记成失败。
        """
        job.error = reason
        if job.attempts >= self.config.max_attempts:
            job.state = FAILED
            return
        try:
            job.state = QUEUED
            self.queue.submit(job)
        except (QueueClosed, QueueFull) as exc:
            job.state = FAILED
            job.error = f"{reason}（无法重投: {type(exc).__name__}）"

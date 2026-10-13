"""The in-process queue between the HTTP intake and the consumers.

接入口与消费者之间的队列。两件和框架有关的事：

**队列建在 ``@start``，不是 ``@init``。** 因为 ``stop()`` 只把 ``start`` 还原成空闲，
``init`` 仍然是"已进入"——在 ``@init`` 里建、在 ``@stop`` 里拆的东西，重启之后不会被
重建。凡是"可回收的资源"都该放在 ``@start``。

**关闸是一个普通方法，不是一个阶段。** ``close()`` 由根单元的 ``@quiesce`` 调用（见
``phases.py``）：停机的第一步是不再接新活，第二步才是把在途的做完。
"""

from __future__ import annotations

import asyncio

from canary_framework import Canary, dep, start, stop

from pipeline.jobs import Job
from pipeline.settings import PipelineSettings


class QueueClosed(Exception):
    """The intake is closed —— 进程正在停机，或者还没启动。"""


class QueueFull(Exception):
    """The lane is backed up —— 接入口不排无限长的队。"""


class JobQueue(Canary):
    """A bounded queue of jobs. Subclass it once per lane.

    有界的任务队列。每条通道一个子类——子类就是图上的另一个节点，所以"同一种东西的多个
    实例"不需要工厂，也不需要命名绑定。
    """

    config = dep(PipelineSettings)

    items: asyncio.Queue[Job]
    closed: bool = True
    #: 停机时还留在队列里、没人做的任务数。
    left_behind: int = 0

    @start
    async def open(self) -> None:
        self.items = asyncio.Queue(maxsize=self.config.queue_size)
        self.closed = False
        self.left_behind = 0

    @stop
    async def shut(self) -> None:
        self.closed = True
        self.left_behind = self.items.qsize()

    def close(self) -> None:
        """Stop accepting new work, keep serving what is already queued.

        不再接新活，已经排上的照做。
        """
        self.closed = True

    def submit(self, job: Job) -> None:
        if self.closed:
            raise QueueClosed(f"{type(self).__name__} is closed")
        try:
            self.items.put_nowait(job)
        except asyncio.QueueFull:
            raise QueueFull(f"{type(self).__name__} is full") from None

    async def take(self) -> Job:
        return await self.items.get()

    @property
    def depth(self) -> int:
        return self.items.qsize() if hasattr(self, "items") else 0

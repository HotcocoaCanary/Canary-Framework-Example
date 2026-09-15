"""Supervised background tasks — still the application's job, not the framework's.

``asyncio.create_task`` 单独用在常驻进程里是不安全的：

* 事件循环只弱引用任务，它可能在运行途中被回收；
* 任务内部的异常被吞掉，直到它被 await 或被 GC；
* 它的生命周期与应用无关，``stop()`` 返回时它可能还在跑。

这个单元解决三件事：持有强引用、记录失败、在 ``@stop`` 里取消并等待全部任务。
0.10.0 的核心依旧只有依赖注入与生命周期，没有任务设施——但它给了一个站得住的挂载点：
回收是唯一路径，正常结束与失败结束共用，所以"没有孤儿任务"这条保证是真的。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from canary_framework import Canary, stop

logger = logging.getLogger("telemetry.tasks")


class SupervisedTasks(Canary):
    def __init__(self) -> None:
        # 单元一律由框架无参构造，所以纯内部状态在 __init__ 里备好；
        # 需要读依赖的事情放到 @init / @start。
        self._tasks: set[asyncio.Task[Any]] = set()
        self._failures: list[tuple[str, BaseException]] = []

    def spawn(self, name: str, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Start *coro* under supervision and keep a strong reference to it."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    @property
    def running(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    @property
    def failures(self) -> list[tuple[str, BaseException]]:
        return list(self._failures)

    @stop
    async def shutdown(self) -> None:
        """Cancel every task and wait for it — no orphans survive the process."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._failures.append((task.get_name(), exc))
            logger.exception("后台任务 %s 异常退出", task.get_name(), exc_info=exc)

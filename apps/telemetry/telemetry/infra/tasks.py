"""Supervised background tasks — the piece Canary does not provide.

``asyncio.create_task`` alone is unsafe in a long-running daemon:

* the task is only weakly referenced by the loop, so it can be garbage-collected
  mid-flight;
* an exception inside it is swallowed until the task is awaited or GC'd;
* nothing ties its lifetime to the application's, so ``Canary.stop()`` returns
  while the task is still running — or the process exits with it half-done.

This unit fixes all three: it holds strong references, records failures, and
cancels-then-awaits everything on ``@on_stop``.  Every Canary project that runs
background work has to write this.  See ``doc/bug/010-no-background-tasks.md``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from canary_framework import cocoa, on_stop

logger = logging.getLogger("telemetry.tasks")


@cocoa
class SupervisedTasks:
    _tasks: set[asyncio.Task[Any]]
    _failures: list[tuple[str, BaseException]]

    def __init__(self) -> None:
        # ``@cocoa`` 单元由框架用 ``t()`` 无参实例化，所以状态在 __init__ 里初始化，
        # 依赖则等 start 阶段注入。
        self._tasks = set()
        self._failures = []

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

    @on_stop
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

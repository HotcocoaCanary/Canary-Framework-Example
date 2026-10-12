"""The background sweep that marks silent devices offline.

后台巡检：心跳超时的设备标记为离线。它和 HTTP 在同一个进程里，是一个**普通单元**——
``@start`` 起循环，``@stop`` 收循环，没有别的机制。

``sweep_once()` 单独暴露出来，是因为时间驱动的东西只有能被手动推进时才谈得上可测：测试
里换一个 ``Clock`` 替身，然后自己调一次。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from canary_framework import Canary, dep, start, stop

from relay.fleet import Fleet
from relay.settings import EdgeSettings

logger = logging.getLogger("relay.reaper")


class Reaper(Canary):
    """Marks devices offline once their heartbeat is overdue.

    心跳过期即标记离线。
    """

    config = dep(EdgeSettings)
    fleet = dep(Fleet)

    sweeps: int = 0
    task: asyncio.Task[None] | None = None

    @start
    async def open(self) -> None:
        self.task = asyncio.create_task(self._loop(), name="relay.reaper")

    @stop
    async def close(self) -> None:
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def sweep_once(self) -> list[str]:
        gone = self.fleet.stale()
        for device in gone:
            self.fleet.mark_offline(device)
        self.sweeps += 1
        return [device.device_id for device in gone]

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.sweep_interval_seconds)
            try:
                if gone := self.sweep_once():
                    logger.info("标记离线: %s", ", ".join(gone))
            except Exception:  # noqa: BLE001 - 巡检不该因为一次失败就停
                logger.exception("巡检失败")

"""遥测守护进程入口 —— 纯核心编排，没有任何 web 依赖。

与场景一的对照点：那里由 FastAPI 的 lifespan 驱动生命周期；这里没有 ASGI，
进程自己用 ``async with TelemetryDaemon()`` 驱动，靠信号退出。框架的
``__aenter__`` / ``__aexit__`` 正好覆盖这个用法。

0.10.0 之后这里没有"容器"了：根单元自己就是入口，``Canary(TelemetryDaemon)``
那一层消失。启动一个单元，它的依赖按依赖顺序就位；退出时逆序回收。
"""

from __future__ import annotations

import asyncio
import logging
import signal

from telemetry.daemon import TelemetryDaemon


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> asyncio.Event:
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    stop = _install_signal_handlers(asyncio.get_running_loop())
    log = logging.getLogger("telemetry")

    async with TelemetryDaemon() as daemon:
        await stop.wait()
        log.info("收到停止信号，最终状态：%s", daemon.status())


if __name__ == "__main__":
    asyncio.run(run())

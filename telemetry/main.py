"""遥测守护进程入口 —— 纯 @cocoa 编排，不使用 web 扩展。

与场景一的对照点：那里 ``Canary`` 是 ASGI 应用，由 uvicorn 的 lifespan 驱动生命周期；
这里没有 ASGI，进程自己用 ``async with Canary(...)`` 驱动，靠信号退出。
框架的 ``__aenter__``/``__aexit__`` 正好覆盖这个用法。

同样值得记录的是：本项目的依赖里**没有** ``canary-framework[web]``，
启动后 ``sys.modules`` 里不含 starlette —— 框架「web 扩展延迟 import」的承诺兑现。

组装到此为止：``Canary(TelemetryDaemon)``，没有第二个参数。最终版删掉了 ``provide=``，
"用哪个采集源 / 哪个告警出口"因此不再是组装期的选择，而是单元自己读 ``AppConfig``
挑后端（见 ``source/sample_source.py`` 与 ``pipeline/sink.py``）。
"""

from __future__ import annotations

import asyncio
import logging
import signal

from canary_framework import Canary
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

    async with Canary(TelemetryDaemon) as app:
        daemon = app[TelemetryDaemon]
        logging.getLogger("telemetry").info(
            "装配完成，%d 个单元：%s",
            len(app.order),
            " → ".join(c.__name__ for c in app.order),
        )
        await stop.wait()
        logging.getLogger("telemetry").info("收到停止信号，最终状态：%s", daemon.status())


if __name__ == "__main__":
    asyncio.run(run())

"""对账单导入流水线 — 入口。

同一份业务，两层 HTTP，用 ``--stack`` 挑一层::

    python main.py                              # canary 版，:8030
    python main.py --stack fastapi              # 原生 FastAPI 版，:8130
    python main.py --stack fastapi --port 9999  # 自己指定端口

信号在这里接：SIGTERM 到了就退出 ``async with``，于是 ``Pipeline.stop()`` 跑完整的两步
停机——先关闸、再排空、最后回收。容器的 ``terminationGracePeriodSeconds`` 要大于
``PIPE_DRAIN_TIMEOUT_SECONDS``，否则第二步会被 SIGKILL 打断。

两层的端口默认差 100（fastapi 版 +100），于是两个栈可以同时起着、用同一个脚本压；
``IngestServer`` 带 ``access_log=False``。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from pipeline.http import NAMES, root
from pipeline.settings import PipelineSettings

#: 原生 FastAPI 版的默认端口在 canary 版上加这个偏移。
OFFSET = {"canary": 0, "fastapi": 100}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对账单导入流水线（两层 HTTP 任选一层）")
    parser.add_argument("--stack", choices=NAMES, default="canary", help="HTTP 层（默认 canary）")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    return parser.parse_args()


async def run(stack: str, port: int | None) -> None:
    log = logging.getLogger("pipeline")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # 端口从配置来（``IngestServer`` 的 ``@init`` 读它），命令行只是改配置的来源：
    # ``Settings`` 就是 pydantic-settings，写进环境变量即可。
    os.environ["PIPE_PORT"] = str(port if port is not None else PipelineSettings().port + OFFSET[stack])

    pipeline = root(stack)()
    async with pipeline:
        log.info("[%s] 接入口 %s", stack, pipeline.status()["listening"])
        await stop.wait()
        log.info("[%s] 收到停止信号，开始两步停机", stack)

    for step in pipeline.journal.entries:
        log.info("  %s", step)
    log.info("[%s] 最终状态: %s", stack, pipeline.status())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    args = parse_args()
    asyncio.run(run(args.stack, args.port))


if __name__ == "__main__":
    main()

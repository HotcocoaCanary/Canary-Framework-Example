"""青瓷商城后台 — 入口：迁移的两个阶段。

    python main.py                 # 阶段一：老应用一行不改，只换服务器（:8040）
    python main.py --stage 2       # 阶段二：新模块与老应用按路径并存（:8041）
    python main.py --stage 2 --port 9000

进程的生命周期归 Canary：``async with Stage2()`` 启动整张图（业务单元、新模块的应用单元），
退出时逆序回收。老应用自己的 lifespan 不再需要——它要的东西都在图上。

两个阶段的区别只有"服务什么"：阶段一服务一个 FastAPI 对象，阶段二服务 ``dispatch`` 拼出来
的两个应用。服务器只认 ASGI 协议，所以这两步都不用动老代码。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from shop.server import STAGES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="青瓷商城后台（迁移的两个阶段）")
    parser.add_argument("--stage", choices=sorted(STAGES), default="1", help="迁移阶段（默认 1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    return parser.parse_args()


async def run(stage: str, port: int | None) -> None:
    log = logging.getLogger("shop")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    server = STAGES[stage]()
    if port is not None:
        server.port = port

    async with server:
        log.info("[阶段 %s] http://%s:%s", stage, server.host, server.port)
        await stop.wait()
        log.info("[阶段 %s] 收到停止信号，回收整张图", stage)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    args = parse_args()
    asyncio.run(run(args.stage, args.port))


if __name__ == "__main__":
    main()

"""门店边缘中继 — 入口。

同一份业务，两层 HTTP，用 ``--stack`` 挑一层::

    python main.py                                      # canary 版：对外 :8020，管理 :9020
    python main.py --stack fastapi                      # 原生 FastAPI 版：对外 :8120，管理 :9120
    python main.py --stack fastapi --public-port 8888   # 自己指定端口

进程的生命周期归 Canary：``async with Relay()`` 启动整张图（两个端口、四个应用、一个巡检
循环），信号由这里自己接，退出时框架逆序回收。

没有 ``uvicorn main:app``——因为这个进程里**不止一个应用，也不止一个端口**，``main:app``
那种写法表达不了。uvicorn 在这里是被 ``Server`` 单元驱动的库，不是进程的主人。

两层的端口默认不同（fastapi 版 +100），于是两个栈可以同时起着、用同一个脚本压。两个
``Server`` 都带 ``access_log=False``。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from relay.http import NAMES, root
from relay.settings import AdminSettings, EdgeSettings

#: 原生 FastAPI 版的默认端口在 canary 版上加这个偏移，于是两个栈能同时起着。
OFFSET = {"canary": 0, "fastapi": 100}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="门店边缘中继（两层 HTTP 任选一层）")
    parser.add_argument("--stack", choices=NAMES, default="canary", help="HTTP 层（默认 canary）")
    parser.add_argument("--public-port", type=int, default=None, help="对外端口")
    parser.add_argument("--admin-port", type=int, default=None, help="管理端口")
    return parser.parse_args()


async def run(stack: str, public_port: int | None, admin_port: int | None) -> None:
    log = logging.getLogger("relay")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # 端口从配置来（``Server`` 的 ``@init`` 读它），命令行只是改那份配置的来源：
    # ``Settings`` 就是 pydantic-settings，所以写进环境变量即可，不必另开一条注入路径。
    offset = OFFSET[stack]
    os.environ["RELAY_PORT"] = str(public_port if public_port is not None else EdgeSettings().port + offset)
    os.environ["ADMIN_PORT"] = str(admin_port if admin_port is not None else AdminSettings().port + offset)

    relay = root(stack)()
    async with relay:
        status = relay.status()
        log.info("[%s] 对外端口 %s", stack, status["public"])
        log.info("[%s] 管理端口 %s  (x-admin-token: %s)", stack, status["admin"], relay.admin.config.token)
        await stop.wait()
        log.info("[%s] 收到停止信号，最终状态: %s", stack, relay.status())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    args = parse_args()
    asyncio.run(run(args.stack, args.public_port, args.admin_port))


if __name__ == "__main__":
    main()

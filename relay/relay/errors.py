"""Domain errors —— 两层 HTTP 共用的那一个。

这个文件只有一个异常类型，**不依赖任何 web 框架**：业务那边 ``raise``，HTTP 那边各自决定
怎么落地。

落地的方式两层不同，这正是两层最实在的差别之一：

* 原生 FastAPI 那层：``app.add_exception_handler(UnknownDevice, ...)``，两个应用各装一次
  （见 ``relay/http/fastapi.py``）；
* 应用单元那层：``@error(UnknownDevice)`` 标记应用单元的方法，两个 ``App`` 各标一次
  （见 ``relay/http/canary.py``）。

两层的报文一模一样（``tests/test_parity.py`` 逐条比过），所以客户端感觉不到。
"""

from __future__ import annotations


class UnknownDevice(Exception):
    """A device id that this relay has never seen.

    没见过的设备号。
    """

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"unknown device: {device_id}")

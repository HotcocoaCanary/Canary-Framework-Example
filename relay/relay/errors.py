"""Domain errors, and the one handler both applications install.

领域异常与落地。值得单独说一句：**异常处理器是每个应用单元各自的**。这个进程里有两个
FastAPI 应用（对外一个、管理口一个），还有一个被它们**共同依赖**的路由单元
（``HealthApi``）——共享的路由抛出来的异常，要在两边各落地一次。所以这里给出一个函数，
两个 ``App`` 的 ``@init`` 各调一次。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class UnknownDevice(Exception):
    """A device id that this relay has never seen.

    没见过的设备号。
    """

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"unknown device: {device_id}")


def install_errors(app: FastAPI) -> None:
    """Map domain errors onto status codes, for one application.

    把领域异常落到状态码上——每个应用一次。
    """

    async def on_unknown_device(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, UnknownDevice)
        return JSONResponse({"detail": str(error), "device_id": error.device_id}, status_code=404)

    app.add_exception_handler(UnknownDevice, on_unknown_device)

"""The FastAPI layer —— routers, the two applications, and the units that listen.

第一层 HTTP：``canary_framework.asgi.fastapi``。和 ``web.py`` 逐行对照，差别只有五处：

* 导入的包；
* 路由单元有 ``tags``，应用单元有类参数（``title`` / ``docs_url`` ……）；
* 成功状态码写 ``status_code=202``（web 版是 ``status=202``）；
* 路径必须写：``@get("")`` 表示"前缀本身"（标记就是 FastAPI 的同名装饰器，录下来重放）；
* 领域异常落在 ``app.add_exception_handler(...)``（web 版是 ``@error(...)`` 标记）。

共用的东西都不在这里：设备台账、计数、配置、巡检、请求模型，以及手写 ASGI 的
``/metrics`` 与 ``/ws/events``。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.asgi.fastapi import App, Router, get, post
from fastapi import Request
from fastapi.responses import JSONResponse

from relay import server
from relay.clock import Clock
from relay.counters import Counters
from relay.errors import UnknownDevice
from relay.fleet import Fleet
from relay.plain import guard
from relay.reaper import Reaper
from relay.schema import Accepted, DeviceEvent, DeviceView, Heartbeat
from relay.settings import AdminSettings, EdgeSettings


class HealthApi(Router, prefix="/health", tags=["健康"]):
    """Liveness and a fleet summary —— **同一个路由单元被两处依赖**。

    对外应用直接依赖它，于是它在 ``/health``；管理应用的 ``AdminRoot``（前缀 ``/admin``）
    也依赖它，于是它同时在 ``/admin/health``。两个 URL，一个实例。
    """

    config = dep(EdgeSettings)
    fleet = dep(Fleet)
    clock = dep(Clock)

    #: 被挂载的次数——用来证明"两处挂载、一个实例"。
    served: int = 0

    @get("")
    async def health(self) -> dict[str, object]:
        self.served += 1
        return {
            "status": "ok",
            "site": self.config.site_id,
            "now": self.clock.now().isoformat(),
            "devices": self.fleet.summary(),
        }


class DevicesApi(Router, prefix="/devices", tags=["设备"]):
    """Heartbeats in, events in, the fleet out."""

    fleet = dep(Fleet)
    counters = dep(Counters)

    @get("")
    async def listing(self, status: str | None = None) -> list[DeviceView]:
        return [DeviceView(**device.view()) for device in self.fleet.all(status)]

    @get("/{device_id}")
    async def one(self, device_id: str) -> DeviceView:
        return DeviceView(**self.require(device_id).view())

    @post("/{device_id}/heartbeat")
    async def heartbeat(self, device_id: str, body: Heartbeat) -> DeviceView:
        device = self.fleet.heartbeat(device_id, body.kind, body.metrics)
        return DeviceView(**device.view())

    @post("/{device_id}/events", status_code=202)
    async def event(self, device_id: str, body: DeviceEvent) -> Accepted:
        self.require(device_id)
        self.fleet.record_event(device_id, body.kind, body.payload)
        return Accepted(type=body.kind, device_id=device_id)

    def require(self, device_id: str):
        """A plain method next to the endpoints —— 路由单元仍然是普通类。"""
        try:
            return self.fleet.require(device_id)
        except KeyError:
            raise UnknownDevice(device_id) from None


class ConsoleApi(Router, prefix="/fleet", tags=["运维"]):
    """Everything the operator can do without logging into the box."""

    config = dep(EdgeSettings)
    fleet = dep(Fleet)
    counters = dep(Counters)
    reaper = dep(Reaper)

    @get("")
    async def overview(self) -> dict[str, object]:
        return {
            "site": self.config.site_id,
            "summary": self.fleet.summary(),
            "sweeps": self.reaper.sweeps,
            "counters": self.counters.snapshot(),
            "devices": [device.view() for device in self.fleet.all()],
        }

    @get("/{device_id}/events")
    async def events(self, device_id: str, limit: int = 20) -> list[dict[str, object]]:
        device = self.require(device_id)
        return list(device.events)[-limit:]

    @post("/{device_id}/quarantine")
    async def quarantine(self, device_id: str, on: bool = True) -> dict[str, object]:
        self.require(device_id)
        return self.fleet.quarantine(device_id, on).view()

    @post("/sweep")
    async def sweep(self) -> dict[str, object]:
        """Run the offline sweep right now —— 和后台循环调的是同一个方法。"""
        return {"offline": self.reaper.sweep_once(), "sweeps": self.reaper.sweeps}

    def require(self, device_id: str):
        try:
            return self.fleet.require(device_id)
        except KeyError:
            raise UnknownDevice(device_id) from None


class AdminRoot(Router, prefix="/admin", tags=["管理"]):
    """Everything under ``/admin`` —— 前缀逐层叠加，共享的 HealthApi 在 ``/admin/health``。"""

    console = dep(ConsoleApi)
    health = dep(HealthApi)


class PublicApi(App, title="门店边缘中继", version="1.0.0"):
    """The store-facing API: ``/devices`` 与 ``/health``。"""

    devices = dep(DevicesApi)
    health = dep(HealthApi)

    @init
    def setup(self) -> None:
        self.app.add_exception_handler(UnknownDevice, on_unknown_device)


class AdminApp(
    App,
    title="边缘中继 · 管理口",
    version="1.0.0",
    docs_url="/admin/docs",
    openapi_url="/admin/openapi.json",
    redoc_url=None,
):
    """The internal API. ``path`` 不是 ``/``，所以 FastAPI 自带的那几个 URL 也要挪进前缀。

    ``docs_url`` 默认是 ``/docs``，而 ``/docs`` 不在 ``/admin`` 之下、根本不会被分发到本
    应用——忘了写就是"接口好的，文档 404"。web 版没有这个问题，因为它没有 OpenAPI。
    """

    config = dep(AdminSettings)
    root = dep(AdminRoot)

    path = "/admin"

    @init
    def setup(self) -> None:
        self.app.add_exception_handler(UnknownDevice, on_unknown_device)
        # 口令校验是一个普通的 ASGI 中间件，两层共用同一份（relay/plain.py）。
        self.app = guard(self.app, self.config.token, "/admin/fleet")


async def on_unknown_device(_: Request, error: Exception) -> JSONResponse:
    """Map the one domain error onto 404 —— 每个应用单元各装一次。"""
    assert isinstance(error, UnknownDevice)
    return JSONResponse({"detail": str(error), "device_id": error.device_id}, status_code=404)


# -- 装配：两个监听的单元与根单元 ------------------------------------------


class PublicServer(server.PublicServer):
    api = dep(PublicApi)


class AdminServer(server.AdminServer):
    console = dep(AdminApp)


class Relay(server.Relay):
    public = dep(PublicServer)
    admin = dep(AdminServer)

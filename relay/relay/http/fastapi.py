"""The native FastAPI layer —— two plain FastAPI applications, served by our ``Server``.

第一层 HTTP：**原生 FastAPI**。两个应用（对外、管理）都是最普通的 FastAPI 写法——模块级
``APIRouter``、普通函数、``Depends``——框架在这里只做两件事：

* 服务器单元在 ``@init`` 里把应用拼好赋给 ``self.app``。对外端口要同时服务 FastAPI 应用、
  ``/metrics`` 与 ``/ws/events`` 两个可调用单元，所以这里用 ``dispatch`` 自己拼；
* 接口通过 ``bridge.use(Cls)`` 从图上按类型取单元。

和 ``canary.py`` 比，差别很直白：那边 ``dep()`` 写在路由单元上、应用单元自己就是 ASGI
应用、服务器 ``dep()`` 一下就完事；这边多一座桥，也多一步手动拼装。换来的是 OpenAPI、
``/docs`` 与 FastAPI 的整套生态。
"""

from __future__ import annotations

from typing import Annotated

from canary_framework import Canary, dep, init
from canary_framework.web.asgi import dispatch
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from relay import server
from relay.clock import Clock
from relay.counters import Counters
from relay.errors import UnknownDevice
from relay.fleet import Fleet
from relay.http.bridge import attach, use
from relay.plain import guard
from relay.reaper import Reaper
from relay.schema import Accepted, DeviceEvent, DeviceView, Heartbeat
from relay.settings import EdgeSettings

Config = Annotated[EdgeSettings, use(EdgeSettings)]
Clocks = Annotated[Clock, use(Clock)]
Devices = Annotated[Fleet, use(Fleet)]
Metering = Annotated[Counters, use(Counters)]
Sweeper = Annotated[Reaper, use(Reaper)]

# -- 对外端口的路由 --------------------------------------------------------

health = APIRouter(prefix="/health", tags=["健康"])
devices = APIRouter(prefix="/devices", tags=["设备"])


@health.get("")
async def site_health(config: Config, fleet: Devices, clock: Clocks) -> dict[str, object]:
    return {
        "status": "ok",
        "site": config.site_id,
        "now": clock.now().isoformat(),
        "devices": fleet.summary(),
    }


def require(fleet: Fleet, device_id: str):
    """The one domain error this API can raise."""
    try:
        return fleet.require(device_id)
    except KeyError:
        raise UnknownDevice(device_id) from None


@devices.get("")
async def listing(fleet: Devices, status: str | None = None) -> list[DeviceView]:
    return [DeviceView(**device.view()) for device in fleet.all(status)]


@devices.get("/{device_id}")
async def one(device_id: str, fleet: Devices) -> DeviceView:
    return DeviceView(**require(fleet, device_id).view())


@devices.post("/{device_id}/heartbeat")
async def heartbeat(device_id: str, body: Heartbeat, fleet: Devices) -> DeviceView:
    device = fleet.heartbeat(device_id, body.kind, body.metrics)
    return DeviceView(**device.view())


@devices.post("/{device_id}/events", status_code=202)
async def event(device_id: str, body: DeviceEvent, fleet: Devices) -> Accepted:
    require(fleet, device_id)
    fleet.record_event(device_id, body.kind, body.payload)
    return Accepted(type=body.kind, device_id=device_id)


# -- 管理端口的路由 --------------------------------------------------------

console = APIRouter(prefix="/admin/fleet", tags=["运维"])


@console.get("")
async def overview(
    config: Config, fleet: Devices, counters: Metering, reaper: Sweeper
) -> dict[str, object]:
    return {
        "site": config.site_id,
        "summary": fleet.summary(),
        "sweeps": reaper.sweeps,
        "counters": counters.snapshot(),
        "devices": [device.view() for device in fleet.all()],
    }


@console.get("/{device_id}/events")
async def events(device_id: str, fleet: Devices, limit: int = 20) -> list[dict[str, object]]:
    device = require(fleet, device_id)
    return list(device.events)[-limit:]


@console.post("/{device_id}/quarantine")
async def quarantine(device_id: str, fleet: Devices, on: bool = True) -> dict[str, object]:
    require(fleet, device_id)
    return fleet.quarantine(device_id, on).view()


@console.post("/sweep")
async def sweep(reaper: Sweeper) -> dict[str, object]:
    """Run the offline sweep right now —— 和后台循环调的是同一个方法。"""
    return {"offline": reaper.sweep_once(), "sweeps": reaper.sweeps}


async def on_unknown_device(_: Request, error: Exception) -> JSONResponse:
    """Map the one domain error onto 404 —— 每个应用各装一次。"""
    assert isinstance(error, UnknownDevice)
    return JSONResponse({"detail": str(error), "device_id": error.device_id}, status_code=404)


def create_public(root: Canary) -> FastAPI:
    """The store-facing application."""
    app = FastAPI(title="门店边缘中继", version="1.0.0")
    app.include_router(devices)
    app.include_router(health)
    app.add_exception_handler(UnknownDevice, on_unknown_device)
    attach(app, root)
    return app


def create_admin(root: Canary) -> FastAPI:
    """The internal application —— 路由自己带着 ``/admin``，文档地址也要挪进去。

    ``dispatch`` 只转发不改写路径，所以这个应用看到的仍是 ``/admin/...``；``docs_url``
    默认是 ``/docs``，不在 ``/admin`` 之下、根本不会被分发到它，所以必须显式写。
    """
    app = FastAPI(
        title="边缘中继 · 管理口",
        version="1.0.0",
        docs_url="/admin/docs",
        openapi_url="/admin/openapi.json",
        redoc_url=None,
    )
    app.include_router(console)
    app.include_router(_admin_health())
    app.add_exception_handler(UnknownDevice, on_unknown_device)
    attach(app, root)
    return app


def _admin_health() -> APIRouter:
    """``/admin/health`` —— 和对外那条**同一个函数**，挂在另一个前缀下。

    对照 ``canary.py``：那边是同一个 ``HealthApi`` **单元**被两处依赖，一个实例、两套 URL；
    这边是同一个函数被两个 ``APIRouter`` 挂两次。两种写法都能共享，差别在"共享的是实例
    还是函数"。
    """
    router = APIRouter(prefix="/admin/health", tags=["健康"])
    router.get("")(site_health)
    return router


# -- 装配：两个监听的单元与根单元 ------------------------------------------


class PublicServer(server.PublicServer):
    """对外端口：FastAPI 应用 + 两个可调用单元，手动 ``dispatch``。

    赋了 ``self.app`` 就以它为准，所以 ``/metrics`` 与 ``/ws/events`` 要自己写进表里——
    canary 层那边只要 ``dep()`` 就行。
    """

    @init
    def build(self) -> None:
        self.app = dispatch(
            {
                self.metrics.path: self.metrics,
                self.stream.path: self.stream,
                "/": create_public(self),
            }
        )


class AdminServer(server.AdminServer):
    """管理端口：FastAPI 应用 + 同一个 ``Metrics`` 实例 + 一个非单元的 ASGI 函数。"""

    @init
    def build(self) -> None:
        admin = guard(create_admin(self), self.config.token, "/admin/fleet")
        self.app = self.assemble(admin)


class Relay(server.Relay):
    public = dep(PublicServer)
    admin = dep(AdminServer)

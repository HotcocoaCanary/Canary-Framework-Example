"""The web layer —— the same HTTP surface, on ``canary_framework.asgi.web``.

第二层 HTTP。和 ``fastapi.py`` 逐行对照，差别只有五处（都在那边的开头列着）。接口方法的
**函数体一个字都没改**——它们本来就只是在调业务单元。

这一层没有的东西：OpenAPI、``/docs``、``tags``、应用单元的类参数。换来的是只依赖
pydantic。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.asgi.web import App, Request, Response, Router, error, get, post

from relay import server
from relay.clock import Clock
from relay.counters import Counters
from relay.errors import UnknownDevice
from relay.fleet import Fleet
from relay.plain import guard
from relay.reaper import Reaper
from relay.schema import Accepted, DeviceEvent, DeviceView, Heartbeat
from relay.settings import AdminSettings, EdgeSettings


class HealthApi(Router, prefix="/health"):
    """Liveness and a fleet summary —— **同一个路由单元被两处依赖**。"""

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


class DevicesApi(Router, prefix="/devices"):
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

    @post("/{device_id}/events", status=202)
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


class ConsoleApi(Router, prefix="/fleet"):
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


class AdminRoot(Router, prefix="/admin"):
    """Everything under ``/admin`` —— 前缀逐层叠加，共享的 HealthApi 在 ``/admin/health``。"""

    console = dep(ConsoleApi)
    health = dep(HealthApi)


class PublicApi(App):
    """The store-facing API: ``/devices`` 与 ``/health``。"""

    devices = dep(DevicesApi)
    health = dep(HealthApi)

    @error(UnknownDevice)
    async def on_unknown_device(self, _: Request, exc: UnknownDevice) -> Response:
        """Map the one domain error onto 404 —— 每个应用单元各标一次。"""
        return Response.json({"detail": str(exc), "device_id": exc.device_id}, status=404)


class AdminApp(App):
    """The internal API. ``path`` 不是 ``/``，但这一层没有 OpenAPI，也就没有要挪的 URL。"""

    config = dep(AdminSettings)
    root = dep(AdminRoot)

    path = "/admin"

    @error(UnknownDevice)
    async def on_unknown_device(self, _: Request, exc: UnknownDevice) -> Response:
        return Response.json({"detail": str(exc), "device_id": exc.device_id}, status=404)

    @init
    def wrap(self) -> None:
        # 口令校验是一个普通的 ASGI 中间件，两层共用同一份（relay/plain.py）。
        self.app = guard(self.app, self.config.token, "/admin/fleet")


# -- 装配：两个监听的单元与根单元 ------------------------------------------


class PublicServer(server.PublicServer):
    api = dep(PublicApi)


class AdminServer(server.AdminServer):
    console = dep(AdminApp)


class Relay(server.Relay):
    public = dep(PublicServer)
    admin = dep(AdminServer)

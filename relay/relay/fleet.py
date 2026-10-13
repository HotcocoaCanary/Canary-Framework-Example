"""The fleet: devices, their heartbeats and their events.

设备台账：心跳、事件、离线判定。它是这个进程里唯一的状态，两个端口上的所有应用都读它。

**事件怎么流到 WebSocket。** 依赖方向是单向的：``EventStream`` 依赖 ``Fleet``，所以 ``Fleet``
不能反过来依赖 ``EventStream``（那是一个环，框架会在任何钩子运行之前就报出来）。于是用最
普通的办法——``Fleet`` 只管广播给登记过的回调，``EventStream`` 在自己的 ``@start`` 里登记。
谁依赖谁决定了谁登记给谁，这一点和框架无关，但框架把它逼得很明确。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from canary_framework import Canary, dep

from relay.clock import Clock
from relay.counters import Counters
from relay.settings import EdgeSettings

#: 广播给订阅者的一条事件。
type Event = dict[str, Any]
type Listener = Callable[[Event], None]


@dataclass(slots=True)
class Device:
    """One device as the relay knows it.

    中继眼里的一台设备。
    """

    device_id: str
    kind: str
    status: str = "online"
    last_seen: datetime | None = None
    heartbeats: int = 0
    quarantined: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    events: deque[Event] = field(default_factory=lambda: deque(maxlen=50))

    def view(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "kind": self.kind,
            "status": "quarantined" if self.quarantined else self.status,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "heartbeats": self.heartbeats,
            "metrics": dict(self.metrics),
        }


class Fleet(Canary):
    """Every device of this site, in memory, with a listener list for live events.

    本站点的全部设备，带一个订阅者列表。
    """

    config = dep(EdgeSettings)
    clock = dep(Clock)
    counters = dep(Counters)

    devices: dict[str, Device]
    listeners: list[Listener]

    def __init__(self) -> None:
        self.devices = {}
        self.listeners = []

    # -- 订阅 ---------------------------------------------------------

    def listen(self, listener: Listener) -> Callable[[], None]:
        """Register *listener*, and return the function that removes it again.

        登记一个订阅者，返回取消登记的函数——``EventStream`` 在 ``@start`` 里登记、在
        ``@stop`` 里取消。
        """
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def publish(self, event: Event) -> None:
        """Hand *event* to every listener. Listeners must not block.

        广播。订阅者不许阻塞——它们只是把事件塞进自己的队列。
        """
        for listener in self.listeners:
            listener(event)

    # -- 心跳与事件 ---------------------------------------------------

    def heartbeat(self, device_id: str, kind: str, metrics: dict[str, float]) -> Device:
        device = self.devices.get(device_id)
        if device is None:
            device = self.devices[device_id] = Device(
                device_id=device_id, kind=kind, events=deque(maxlen=self.config.event_history)
            )
            self.counters.incr("relay_devices_seen_total")
            self.publish({"type": "device.new", "device_id": device_id, "kind": kind})
        device.kind = kind
        device.heartbeats += 1
        device.last_seen = self.clock.now()
        device.metrics.update(metrics)
        if device.status != "online":
            device.status = "online"
            self.publish({"type": "device.online", "device_id": device_id})
        self.counters.incr("relay_heartbeats_total")
        return device

    def record_event(self, device_id: str, kind: str, payload: dict[str, Any]) -> Event:
        device = self.devices.get(device_id)
        event: Event = {
            "type": "device.event",
            "device_id": device_id,
            "kind": kind,
            "payload": payload,
            "at": self.clock.now().isoformat(),
        }
        if device is not None:
            device.events.append(event)
        self.counters.incr("relay_events_total")
        self.publish(event)
        return event

    def quarantine(self, device_id: str, on: bool) -> Device:
        device = self.require(device_id)
        device.quarantined = on
        self.counters.incr("relay_quarantine_changes_total")
        self.publish(
            {"type": "device.quarantined" if on else "device.released", "device_id": device_id}
        )
        return device

    # -- 查询 ---------------------------------------------------------

    def require(self, device_id: str) -> Device:
        device = self.devices.get(device_id)
        if device is None:
            raise KeyError(device_id)
        return device

    def all(self, status: str | None = None) -> list[Device]:
        found = sorted(self.devices.values(), key=lambda d: d.device_id)
        if status is None:
            return found
        return [d for d in found if d.view()["status"] == status]

    def stale(self) -> list[Device]:
        """Devices whose last heartbeat is older than the timeout.

        心跳超时的设备。时间从 ``Clock`` 读，所以测试里可以手动推。
        """
        now = self.clock.now()
        timeout = self.config.heartbeat_timeout_seconds
        return [
            device
            for device in self.devices.values()
            if device.status == "online"
            and device.last_seen is not None
            and (now - device.last_seen).total_seconds() > timeout
        ]

    def mark_offline(self, device: Device) -> None:
        device.status = "offline"
        self.counters.incr("relay_offline_total")
        self.publish({"type": "device.offline", "device_id": device.device_id})

    def summary(self) -> dict[str, int]:
        by_status: dict[str, int] = {}
        for device in self.devices.values():
            key = device.view()["status"]
            by_status[key] = by_status.get(key, 0) + 1
        return by_status

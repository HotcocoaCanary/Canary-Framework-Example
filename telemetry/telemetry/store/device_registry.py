"""The monitored fleet and the rules attached to each device."""

from __future__ import annotations

from canary_framework import Canary, dep, start

from telemetry.domain.models import Device, Threshold
from telemetry.settings import AppConfig

_SEED = (
    Device(
        id="rack-a-temp",
        name="A 排机柜温度",
        kind="thermometer",
        metrics=("temperature", "humidity"),
        thresholds={
            # 阈值留在合成基线之上：一个默认就满屏告警的监控系统等于没有监控。
            # 基线波形见 source/sample_source.py::_WAVEFORMS。
            "temperature": Threshold(warning=35.0, critical=40.0),
            "humidity": Threshold(warning=72.0, critical=85.0),
        },
    ),
    Device(
        id="rack-b-power",
        name="B 排机柜功耗",
        kind="power-meter",
        metrics=("watts",),
        thresholds={"watts": Threshold(warning=4700.0, critical=5200.0)},
    ),
    Device(
        id="gateway-01",
        name="边缘网关",
        kind="gateway",
        metrics=("cpu", "latency_ms"),
        thresholds={
            "cpu": Threshold(warning=88.0, critical=95.0),
            "latency_ms": Threshold(warning=250.0, critical=500.0),
        },
    ),
)


class DeviceRegistry(Canary):
    config = dep(AppConfig)

    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    @start
    async def setup(self) -> None:
        for device in _SEED:
            if device.offline_after_seconds is None:
                device.offline_after_seconds = self.config.offline_after_seconds
            self._devices[device.id] = device

    def add(self, device: Device) -> Device:
        if device.offline_after_seconds is None:
            device.offline_after_seconds = self.config.offline_after_seconds
        self._devices[device.id] = device
        return device

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def enabled(self) -> list[Device]:
        return [d for d in self._devices.values() if d.enabled]

    def all(self) -> list[Device]:
        return list(self._devices.values())

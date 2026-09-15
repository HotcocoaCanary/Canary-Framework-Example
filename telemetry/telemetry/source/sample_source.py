"""Where readings come from — synthetic waveforms, or an HTTP endpoint.

``SampleSource`` 是确定性的：给定 (设备, 指标, 时刻) 的值永远相同，所以守护进程的
测试可以断言精确的告警输出。``HttpSampleBackend`` 轮询一个形如
``{"samples": [{"device_id","metric","value","at"}]}`` 的 JSON 端点。

"用哪个后端"由单元自己读 ``AppConfig`` 决定——框架没有装配期的替换入口，图上的实例
一律由框架无参构造。整个单元被换掉是另一回事，那条路留给测试，见 ``telemetry/testing.py``。
"""

from __future__ import annotations

import logging
import math

import httpx
from canary_framework import Canary, dep, start, stop

from telemetry.domain.models import Sample
from telemetry.infra.clock import Clock
from telemetry.settings import AppConfig
from telemetry.store.device_registry import DeviceRegistry

logger = logging.getLogger("telemetry.source")

# 每个指标一条确定性波形：(基线, 振幅, 周期秒)
_WAVEFORMS: dict[str, tuple[float, float, float]] = {
    "temperature": (28.0, 6.0, 60.0),
    "humidity": (55.0, 12.0, 90.0),
    "watts": (3800.0, 700.0, 45.0),
    "cpu": (55.0, 30.0, 30.0),
    "latency_ms": (120.0, 90.0, 75.0),
}


class SampleSource(Canary):
    """Deterministic synthetic waveforms — or, when configured, an HTTP endpoint."""

    config = dep(AppConfig)
    clock = dep(Clock)
    devices = dep(DeviceRegistry)

    def __init__(self) -> None:
        self._boost: dict[tuple[str, str], float] = {}
        self._remote: HttpSampleBackend | None = None

    @start
    async def choose_backend(self) -> None:
        if self.config.use_http_source:
            self._remote = HttpSampleBackend(self.config)
            await self._remote.open()

    @stop
    async def close_backend(self) -> None:
        if self._remote is not None:
            await self._remote.aclose()
            self._remote = None

    async def read(self) -> list[Sample]:
        if self._remote is not None:
            return await self._remote.read()
        now = self.clock.now()
        samples: list[Sample] = []
        for device in self.devices.enabled():
            for metric in device.metrics:
                base, amplitude, period = _WAVEFORMS.get(metric, (50.0, 10.0, 60.0))
                phase = math.sin(2 * math.pi * (now % period) / period)
                value = base + amplitude * phase + self._boost.get((device.id, metric), 0.0)
                samples.append(
                    Sample(device_id=device.id, metric=metric, value=round(value, 3), at=now)
                )
        return samples

    def force(self, device_id: str, metric: str, offset: float) -> None:
        """Bias one series — lets a test drive a device into alert territory."""
        self._boost[(device_id, metric)] = offset


class HttpSampleBackend:
    """Polls a JSON endpoint.

    不在图上：由 ``SampleSource`` 构造并持有，因此**没有**生命周期钩子——
    ``@start`` / ``@stop`` 只对图上的单元有效，开关连接由持有者转发。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.config.source_timeout_seconds)

    async def aclose(self) -> None:
        # 容忍「open() 只跑了一半」的自己：启动失败时这个方法照样会被调用。
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def read(self) -> list[Sample]:
        assert self._client is not None, "HttpSampleBackend 尚未 open()"
        response = await self._client.get(self.config.source_url)
        response.raise_for_status()
        payload = response.json()
        return [
            Sample(
                device_id=row["device_id"],
                metric=row["metric"],
                value=float(row["value"]),
                at=float(row["at"]),
            )
            for row in payload.get("samples", [])
        ]

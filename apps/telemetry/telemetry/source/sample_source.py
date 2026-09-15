"""Where readings come from — synthetic waveforms, or an HTTP endpoint.

``SampleSource`` is deterministic: the value for a given (device, metric, tick)
is always the same, so a daemon test can assert exact alert output.
``HttpSampleSource`` polls a JSON endpoint shaped like
``{"samples": [{"device_id","metric","value"}]}`` and is substituted in by
``main.py`` when the settings ask for it.

0.9.3 的 ``provide=`` 曾让"用哪个采集源"成为组装期的选择；最终版把那个入口删了，
于是决定权回到单元自己手里：``SampleSource`` 读 ``AppConfig``，需要时在 ``@on_start``
换上 HTTP 后端并把 ``read()`` 转过去。后端不在图上，所以它的开关连接也由这里转发。
"""

from __future__ import annotations

import logging
import math

import httpx

from canary_framework import cocoa, on_start, on_stop
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


@cocoa(deps=[AppConfig, Clock, DeviceRegistry])
class SampleSource:
    """Deterministic synthetic waveforms — or, when configured, an HTTP endpoint."""

    app_config: AppConfig
    clock: Clock
    device_registry: DeviceRegistry

    _remote: HttpSampleBackend | None = None

    _boost: dict[tuple[str, str], float]

    def __init__(self) -> None:
        self._boost = {}

    @on_start
    async def choose_backend(self) -> None:
        if self.app_config.use_http_source:
            self._remote = HttpSampleBackend(self.app_config)
            await self._remote.open()

    @on_stop
    async def close_backend(self) -> None:
        if self._remote is not None:
            await self._remote.aclose()
            self._remote = None

    async def read(self) -> list[Sample]:
        if self._remote is not None:
            return await self._remote.read()
        now = self.clock.now()
        samples: list[Sample] = []
        for device in self.device_registry.enabled():
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
    """Polls a JSON endpoint. 不在图上：由 ``SampleSource`` 构造并持有。

    因此它**没有**生命周期钩子——``@on_start`` / ``@on_stop`` 只对图上的节点有效，
    开关连接由持有者转发。
    """

    _client: httpx.AsyncClient | None = None

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config

    async def open(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.app_config.source_timeout_seconds)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def read(self) -> list[Sample]:
        assert self._client is not None, "HttpSampleBackend 尚未 open()"
        response = await self._client.get(self.app_config.source_url)
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



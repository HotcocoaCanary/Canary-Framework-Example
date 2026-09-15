"""Tumbling-window aggregation over the metric store."""

from __future__ import annotations

import math

from canary_framework import Canary, dep

from telemetry.domain.models import WindowStat
from telemetry.infra.clock import Clock
from telemetry.settings import AppConfig
from telemetry.store.device_registry import DeviceRegistry
from telemetry.store.metric_store import MetricStore


class WindowAggregator(Canary):
    config = dep(AppConfig)
    clock = dep(Clock)
    store = dep(MetricStore)
    devices = dep(DeviceRegistry)

    def current(self) -> list[WindowStat]:
        """Aggregate the most recent window for every enabled (device, metric)."""
        until = self.clock.now()
        since = until - self.config.window_seconds
        stats: list[WindowStat] = []
        for device in self.devices.enabled():
            for metric in device.metrics:
                samples = self.store.window(device.id, metric, since=since, until=until)
                if not samples:
                    continue
                stats.append(_summarise(device.id, metric, samples, since, until))
        return stats


def _summarise(device_id, metric, samples, since, until) -> WindowStat:
    values = sorted(s.value for s in samples)
    return WindowStat(
        device_id=device_id,
        metric=metric,
        count=len(values),
        avg=sum(values) / len(values),
        minimum=values[0],
        maximum=values[-1],
        p95=values[_percentile_index(len(values), 0.95)],
        window_start=since,
        window_end=until,
    )


def _percentile_index(size: int, q: float) -> int:
    """Nearest-rank percentile index, clamped into range."""
    return min(max(math.ceil(q * size) - 1, 0), size - 1)

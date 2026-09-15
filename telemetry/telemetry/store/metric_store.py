"""In-memory time series — one bounded ring buffer per (device, metric).

Bounded on purpose: a daemon runs for weeks, so an unbounded buffer is a slow
memory leak.  ``series_capacity`` caps each series, and old samples fall off the
back.
"""

from __future__ import annotations

from collections import deque

from canary_framework import Canary, dep, start

from telemetry.domain.models import Sample
from telemetry.settings import AppConfig


class MetricStore(Canary):
    config = dep(AppConfig)

    def __init__(self) -> None:
        self._series: dict[tuple[str, str], deque[Sample]] = {}
        self._capacity = 600

    @start
    async def setup(self) -> None:
        # 依赖从 @init 起可用，所以这里读得到配置。
        self._capacity = self.config.series_capacity

    def record(self, sample: Sample) -> None:
        key = (sample.device_id, sample.metric)
        series = self._series.get(key)
        if series is None:
            series = self._series[key] = deque(maxlen=self._capacity)
        series.append(sample)

    def record_many(self, samples: list[Sample]) -> int:
        for sample in samples:
            self.record(sample)
        return len(samples)

    def window(
        self, device_id: str, metric: str, *, since: float, until: float
    ) -> list[Sample]:
        """Samples with ``since <= at <= until``, oldest first."""
        series = self._series.get((device_id, metric))
        if not series:
            return []
        return [s for s in series if since <= s.at <= until]

    def latest(self, device_id: str, metric: str) -> Sample | None:
        series = self._series.get((device_id, metric))
        return series[-1] if series else None

    def last_seen(self, device_id: str) -> float | None:
        """The most recent sample time across all of a device's metrics."""
        times = [
            series[-1].at
            for (dev, _), series in self._series.items()
            if dev == device_id and series
        ]
        return max(times) if times else None

    def series_keys(self) -> list[tuple[str, str]]:
        return list(self._series)

    def total_samples(self) -> int:
        return sum(len(s) for s in self._series.values())

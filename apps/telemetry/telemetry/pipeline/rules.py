"""Rule evaluation — turns window statistics into alerts.

Three rules, in the order a human would check them:

1. **offline** — the device has stopped reporting entirely.  Checked first,
   because a silent device makes every other rule meaningless.
2. **threshold** — the window average crossed the device's warning/critical line.
3. **rate** — the window average moved by more than ``rate_change_ratio``
   relative to the previous window, even if it is still under the threshold.
   This is what catches a fan failure before the temperature alarm fires.
"""

from __future__ import annotations

from telemetry.domain.models import Alert, AlertKind, Severity, WindowStat
from telemetry.infra.clock import Clock
from telemetry.store.device_registry import DeviceRegistry
from telemetry.store.metric_store import MetricStore
from canary_framework import cocoa
from telemetry.settings import AppConfig


@cocoa(deps=[AppConfig, Clock, DeviceRegistry, MetricStore])
class RuleEngine:
    app_config: AppConfig
    clock: Clock
    device_registry: DeviceRegistry
    metric_store: MetricStore

    _previous: dict[tuple[str, str], float]

    def __init__(self) -> None:
        self._previous = {}

    def evaluate(self, stats: list[WindowStat]) -> list[Alert]:
        now = self.clock.now()
        alerts: list[Alert] = [*self._offline_alerts(now)]
        offline = {a.device_id for a in alerts}

        for stat in stats:
            if stat.device_id in offline:
                continue
            alerts.extend(self._threshold_alerts(stat, now))
            alerts.extend(self._rate_alerts(stat, now))
            self._previous[(stat.device_id, stat.metric)] = stat.avg
        return alerts

    # -- 规则 1：离线 ---------------------------------------------------
    def _offline_alerts(self, now: float) -> list[Alert]:
        alerts = []
        for device in self.device_registry.enabled():
            deadline = device.offline_after_seconds or self.app_config.offline_after_seconds
            last = self.metric_store.last_seen(device.id)
            if last is None or now - last <= deadline:
                continue
            alerts.append(
                Alert(
                    device_id=device.id,
                    metric="*",
                    kind=AlertKind.OFFLINE,
                    severity=Severity.CRITICAL,
                    value=now - last,
                    message=f"{device.name} 已 {now - last:.0f} 秒无数据上报",
                    at=now,
                )
            )
        return alerts

    # -- 规则 2：阈值 ---------------------------------------------------
    def _threshold_alerts(self, stat: WindowStat, now: float) -> list[Alert]:
        device = self.device_registry.get(stat.device_id)
        threshold = device.thresholds.get(stat.metric) if device else None
        if threshold is None:
            return []
        severity = threshold.severity_for(stat.avg)
        if severity is None:
            return []
        limit = threshold.critical if severity is Severity.CRITICAL else threshold.warning
        return [
            Alert(
                device_id=stat.device_id,
                metric=stat.metric,
                kind=AlertKind.THRESHOLD,
                severity=severity,
                value=stat.avg,
                message=(
                    f"{device.name} 的 {stat.metric} 窗口均值 {stat.avg:.1f} "
                    f"超过{'严重' if severity is Severity.CRITICAL else '警告'}线 {limit:.1f}"
                ),
                at=now,
            )
        ]

    # -- 规则 3：变化率 -------------------------------------------------
    def _rate_alerts(self, stat: WindowStat, now: float) -> list[Alert]:
        previous = self._previous.get((stat.device_id, stat.metric))
        if previous is None or previous == 0:
            return []
        ratio = abs(stat.avg - previous) / abs(previous)
        if ratio < self.app_config.rate_change_ratio:
            return []
        device = self.device_registry.get(stat.device_id)
        direction = "上升" if stat.avg > previous else "下降"
        return [
            Alert(
                device_id=stat.device_id,
                metric=stat.metric,
                kind=AlertKind.RATE,
                severity=Severity.WARNING,
                value=ratio,
                message=(
                    f"{device.name if device else stat.device_id} 的 {stat.metric} "
                    f"较上一窗口{direction} {ratio:.0%}（{previous:.1f} → {stat.avg:.1f}）"
                ),
                at=now,
            )
        ]

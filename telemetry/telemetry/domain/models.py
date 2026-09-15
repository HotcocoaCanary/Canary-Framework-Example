"""The telemetry domain — plain values, no ORM.

Scenario 2 keeps everything in memory on purpose: it isolates the framework's
*lifecycle* behaviour from the storage concerns that dominated scenario 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class AlertKind(StrEnum):
    THRESHOLD = "threshold"
    RATE = "rate"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class Sample:
    """One reading from one device."""

    device_id: str
    metric: str
    value: float
    at: float  # epoch seconds


@dataclass(frozen=True, slots=True)
class Threshold:
    warning: float
    critical: float

    def severity_for(self, value: float) -> Severity | None:
        if value >= self.critical:
            return Severity.CRITICAL
        if value >= self.warning:
            return Severity.WARNING
        return None


@dataclass(slots=True)
class Device:
    """A monitored device and the rules that apply to it."""

    id: str
    name: str
    kind: str = "sensor"
    metrics: tuple[str, ...] = ()
    thresholds: dict[str, Threshold] = field(default_factory=dict)
    offline_after_seconds: float | None = None
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class WindowStat:
    """Aggregate of one (device, metric) over one time window."""

    device_id: str
    metric: str
    count: int
    avg: float
    minimum: float
    maximum: float
    p95: float
    window_start: float
    window_end: float


@dataclass(frozen=True, slots=True)
class Alert:
    device_id: str
    metric: str
    kind: AlertKind
    severity: Severity
    value: float
    message: str
    at: float

    @property
    def fingerprint(self) -> str:
        """What the dispatcher de-duplicates on."""
        return f"{self.device_id}|{self.metric}|{self.kind.value}|{self.severity.value}"

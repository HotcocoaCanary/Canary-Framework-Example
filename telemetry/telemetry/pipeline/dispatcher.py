"""Alert delivery policy — de-duplication and cooldown.  Delivery itself is the sink's.

Without a cooldown a threshold breach re-fires on every evaluation tick, which
is how monitoring systems train their operators to ignore them.  Alerts are
fingerprinted on (device, metric, kind, severity); the same fingerprint is
suppressed until ``alert_cooldown_seconds`` has passed.
"""

from __future__ import annotations

import logging
from collections import deque

from canary_framework import cocoa, on_start
from telemetry.domain.models import Alert
from telemetry.infra.clock import Clock
from telemetry.pipeline.sink import LoggingAlertSink
from telemetry.settings import AppConfig

logger = logging.getLogger("telemetry.alerts")


@cocoa(deps=[AppConfig, Clock, LoggingAlertSink])
class AlertDispatcher:
    app_config: AppConfig
    clock: Clock
    logging_alert_sink: LoggingAlertSink

    _last_sent: dict[str, float]
    _history: deque[Alert]
    _delivered: int
    _suppressed: int

    def __init__(self) -> None:
        self._last_sent = {}
        self._history = deque(maxlen=500)
        self._delivered = 0
        self._suppressed = 0

    @on_start
    async def setup(self) -> None:
        self._history = deque(maxlen=self.app_config.alert_history_size)

    async def dispatch(self, alerts: list[Alert]) -> list[Alert]:
        """Deliver the alerts that survive de-duplication; return those sent."""
        sent: list[Alert] = []
        for alert in alerts:
            if self._suppress(alert):
                self._suppressed += 1
                continue
            self._last_sent[alert.fingerprint] = alert.at
            self._history.append(alert)
            await self.logging_alert_sink.deliver(alert)
            self._delivered += 1
            sent.append(alert)
        return sent

    @property
    def history(self) -> list[Alert]:
        return list(self._history)

    @property
    def stats(self) -> dict[str, int]:
        return {"delivered": self._delivered, "suppressed": self._suppressed}

    def _suppress(self, alert: Alert) -> bool:
        previous = self._last_sent.get(alert.fingerprint)
        if previous is None:
            return False
        return alert.at - previous < self.app_config.alert_cooldown_seconds

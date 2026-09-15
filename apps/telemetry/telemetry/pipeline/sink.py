"""Where a surviving alert actually goes.

Split out of ``AlertDispatcher``: de-duplication is policy and belongs to the
dispatcher, delivery is I/O and belongs here.  默认写日志；``AppConfig`` 说要
webhook 时，在 ``@on_start`` 换上 HTTP 后端——最终版删掉了 ``provide=``，
"投递到哪儿"因此是单元自己读配置决定的。
"""

from __future__ import annotations

import logging

import httpx

from canary_framework import cocoa, on_start, on_stop
from telemetry.domain.models import Alert
from telemetry.settings import AppConfig

logger = logging.getLogger("telemetry.alerts")


@cocoa(deps=[AppConfig])
class LoggingAlertSink:
    """Writes the alert to the log — the default, and what tests assert against."""

    app_config: AppConfig

    delivered: list[Alert]
    _remote: WebhookBackend | None = None

    def __init__(self) -> None:
        self.delivered = []

    @on_start
    async def choose_backend(self) -> None:
        if self.app_config.use_webhook_sink:
            self._remote = WebhookBackend(self.app_config)
            await self._remote.open()

    @on_stop
    async def close_backend(self) -> None:
        if self._remote is not None:
            await self._remote.aclose()
            self._remote = None

    async def deliver(self, alert: Alert) -> None:
        self.delivered.append(alert)
        if self._remote is not None:
            await self._remote.deliver(alert)
            return
        logger.warning("[%s] %s", alert.severity.value.upper(), alert.message)


class WebhookBackend:
    """POSTs the alert to ``alert_webhook_url``. 不在图上，由 ``LoggingAlertSink`` 持有。"""

    _client: httpx.AsyncClient | None = None

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config

    async def open(self) -> None:
        self._client = httpx.AsyncClient(timeout=5.0)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def deliver(self, alert: Alert) -> None:
        assert self._client is not None, "WebhookBackend 尚未 open()"
        # 投递失败不应让整个评估 tick 崩掉——告警管道要尽力送达。
        try:
            response = await self._client.post(
                self.app_config.alert_webhook_url,
                json={
                    "device_id": alert.device_id,
                    "metric": alert.metric,
                    "kind": alert.kind.value,
                    "severity": alert.severity.value,
                    "value": alert.value,
                    "message": alert.message,
                    "at": alert.at,
                },
            )
            response.raise_for_status()
        except Exception:
            logger.exception("告警投递失败: %s", alert.fingerprint)

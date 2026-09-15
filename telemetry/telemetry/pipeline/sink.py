"""Where a surviving alert actually goes.

从 ``AlertDispatcher`` 里拆出来：去重是策略，归调度器；投递是 I/O，归这里。
默认写日志；``AppConfig`` 说要 webhook 时，在 ``@start`` 换上 HTTP 后端。

"用哪个后端"由单元自己读配置决定：框架没有装配期的替换入口，图上的实例一律由框架
无参构造。测试要整个换掉一个单元走的是另一条路——把替身预先登记进作用域，
见 ``telemetry/testing.py``。
"""

from __future__ import annotations

import logging

import httpx
from canary_framework import Canary, dep, start, stop

from telemetry.domain.models import Alert
from telemetry.settings import AppConfig

logger = logging.getLogger("telemetry.alerts")


class LoggingAlertSink(Canary):
    """Writes the alert to the log — the default, and what tests assert against."""

    config = dep(AppConfig)

    def __init__(self) -> None:
        self.delivered: list[Alert] = []
        self._remote: WebhookBackend | None = None

    @start
    async def choose_backend(self) -> None:
        if self.config.use_webhook_sink:
            self._remote = WebhookBackend(self.config)
            await self._remote.open()

    @stop
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
    """POSTs the alert to ``alert_webhook_url``.

    不在图上：由 ``LoggingAlertSink`` 构造并持有，因此**没有**生命周期钩子——
    ``@start`` / ``@stop`` 只对图上的单元有效，开关连接由持有者转发。
    """

    _client: httpx.AsyncClient | None = None

    def __init__(self, config: AppConfig) -> None:
        self.config = config

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
                self.config.alert_webhook_url,
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

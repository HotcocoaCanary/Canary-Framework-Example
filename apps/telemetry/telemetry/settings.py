"""Settings for the telemetry daemon — a plain ``@cocoa`` unit.

Same shape as scenario 1's ``config.py``, and for the same reason: the beta
deleted class-level annotation injection (and the ``canary_framework.Config``
base class with it), so configuration is an ordinary node on the graph again.
Whoever needs it writes ``AppConfig`` into its own ``deps=[...]`` and reads
``self.app_config``.

``use_http_source`` / ``use_webhook_sink`` 是"用哪个实现"的开关。它们曾在 0.9.3 的
``provide=`` 时代被删掉过（选择搬到了组装期），最终版删掉那个入口之后又回来了——
现在由单元自己在 ``@on_start`` 里读它们挑后端。这笔账记在 doc/verification-final.md。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from canary_framework import cocoa


@cocoa
class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # -- 采集 ----------------------------------------------------------
    source_url: str = "http://localhost:9100/metrics"
    source_timeout_seconds: float = 5.0

    collect_interval_seconds: float = 1.0
    evaluate_interval_seconds: float = 5.0

    # -- 存储 ----------------------------------------------------------
    # 每个 (设备, 指标) 保留的样本数——环形缓冲，内存占用有上界
    series_capacity: int = 600

    # -- 规则 ----------------------------------------------------------
    window_seconds: float = 30.0
    rate_change_ratio: float = 0.5
    offline_after_seconds: float = 30.0

    # -- 告警 ----------------------------------------------------------
    alert_webhook_url: str = "http://localhost:9200/alerts"
    alert_cooldown_seconds: float = 300.0
    alert_history_size: int = 500

    # -- 装配开关 ------------------------------------------------------
    # 这两个不是"实现分支"，而是 main.py 决定往 provide 里放什么的输入。
    # 单元自身完全不认识它们。
    use_http_source: bool = False
    use_webhook_sink: bool = False

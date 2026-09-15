"""Settings for the telemetry daemon — a unit that is also a pydantic model.

0.10.0 的单元就是普通 Python 类，所以配置不必在"pydantic 模型"和"图上的节点"之间
二选一——两个基类一起继承即可::

    class AppConfig(BaseSettings, Canary): ...

``BaseSettings`` 负责读 ``.env`` 与环境变量，``Canary`` 让它成为图上的一个节点，
于是谁要用谁写 ``config = dep(AppConfig)``，整张图共享同一个实例。

0.9.x 做不到这件事：``@cocoa`` 是装饰器，改不了类的静态类型；配置一度还被做成框架
特有的"类级注解即声明"注入源，连带一个 ``canary_framework.Config`` 基类。现在配置
既没有特殊地位，也不需要特殊写法。

``use_http_source`` / ``use_webhook_sink`` 是"用哪个后端"的开关，由 ``SampleSource``
与 ``LoggingAlertSink`` 自己在 ``@start`` 里读。测试要整个换掉某个单元则是另一条路，
见 ``telemetry/testing.py``。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from canary_framework import Canary


class AppConfig(BaseSettings, Canary):
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

    # -- 后端选择 ------------------------------------------------------
    use_http_source: bool = False
    use_webhook_sink: bool = False

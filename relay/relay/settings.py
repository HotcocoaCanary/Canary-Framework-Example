"""Two settings units in one process — one per port, plus one that has a dependency.

一个进程里的两份配置。``canary_framework.config.Settings`` 是 ``BaseSettings`` 加
``Canary``，所以"多份配置"就是**多个单元**：各读自己的 ``env_prefix``，共享同一个
``.env``，整张图各自共享一个实例。

``AdminSettings`` 顺带压了两件文档里提到但 ``library`` 没碰到的事：

* **配置可以有依赖**：``secrets = dep(SecretStore)`` 写在模型里不会被 pydantic 当成字段；
* **配置可以有钩子**：``@init`` 里补一个字段的值。赋值的属性必须是声明过的字段，这是
  pydantic 的规则，不是框架的。

时序上有一条要记住：钩子能用到的只是依赖在 ``@init`` 之后的状态。``init`` 阶段依赖在前，
所以 ``SecretStore.@init`` 早于这里；但依赖的 ``@start`` 比这里**晚**，取不到。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.config import Settings
from pydantic_settings import SettingsConfigDict

from relay.secrets import SecretStore


class EdgeSettings(Settings):
    """The public port and the fleet rules —— ``RELAY_*``."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RELAY_", extra="ignore")

    site_id: str = "shop-001"

    host: str = "0.0.0.0"
    port: int = 8020

    #: 多久没有心跳就算离线。
    heartbeat_timeout_seconds: float = 90.0
    #: 巡检间隔。
    sweep_interval_seconds: float = 15.0
    #: 每个 WebSocket 客户端的积压上限，满了就丢最旧的——边缘带宽比历史事件重要。
    stream_queue_size: int = 64
    #: 每台设备留多少条最近事件。
    event_history: int = 50


class AdminSettings(Settings):
    """The internal admin port —— ``ADMIN_*``，口令可以来自 ``SecretStore``。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ADMIN_", extra="ignore")

    secrets = dep(SecretStore)

    host: str = "127.0.0.1"
    port: int = 9020
    token: str = ""

    @init
    def fill_in_token(self) -> None:
        if not self.token:
            self.token = self.secrets.read("admin-token")

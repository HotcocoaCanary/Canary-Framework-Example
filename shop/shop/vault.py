"""The key store the payment settings read from.

支付配置读密钥的地方。它存在是为了让 ``PaymentSettings`` 有一个**依赖**——配置自己也是
单元，可以依赖别的单元、也可以有钩子。

和 ``relay`` 里那个 ``SecretStore`` 一样，它必须在 ``@init`` 里把值准备好：依赖它的那份
配置是在 ``@init`` 里取值的，而依赖的 ``@start`` 比那更晚。
"""

from __future__ import annotations

import os

from canary_framework import Canary, init


class Vault(Canary):
    """Keys, from the environment or from a deterministic dev fallback.

    密钥。线上由密钥系统注入环境变量，开发机上退化成一个确定性的假值——不是随机的，
    否则每次重启签名都变。
    """

    keys: dict[str, str]

    @init
    def load(self) -> None:
        self.keys = {
            name[6:].lower(): value
            for name, value in os.environ.items()
            if name.startswith("VAULT_")
        }

    def read(self, name: str) -> str:
        return self.keys.get(name, f"dev-key-{name}")

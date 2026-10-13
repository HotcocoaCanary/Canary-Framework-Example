"""The local secret file on the edge box.

边缘机上的本地密钥文件。它存在的唯一理由是给 ``AdminSettings`` 一个**依赖**：配置本身
也是单元，可以依赖别的单元、也可以有钩子（见 ``settings.py``）。

它在 ``@init`` 里读文件，而不是 ``@start``。因为依赖它的那份配置是在 ``@init`` 里取值的：
``init`` 阶段依赖在前，所以 ``SecretStore.@init`` 一定早于 ``AdminSettings.@init``；但
``@start`` 就太晚了。配置的依赖要把值准备在 ``@init``。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from canary_framework import Canary, init


class SecretStore(Canary):
    """Secrets read from a JSON file, with a deterministic fallback for dev boxes.

    从 JSON 文件读密钥；文件不存在时按站点名派生一个确定性的开发口令——边缘机常常是
    "先跑起来再配"，但口令不能是随机的，否则重启之后运维手上的那个就失效了。
    """

    values: dict[str, str]

    @init
    def load(self) -> None:
        path = Path(os.environ.get("SECRETS_FILE", "secrets.json"))
        if path.exists():
            self.values = {str(k): str(v) for k, v in json.loads(path.read_text()).items()}
        else:
            self.values = {}

    def read(self, name: str) -> str:
        if name in self.values:
            return self.values[name]
        digest = hashlib.sha256(f"canary-relay/{name}".encode()).hexdigest()
        return f"dev-{digest[:16]}"

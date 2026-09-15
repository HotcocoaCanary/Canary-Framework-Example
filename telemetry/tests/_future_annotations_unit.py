"""A unit declared under ``from __future__ import annotations``.

0.9.x 的类级注解注入在这个文件里会静默失效——注解是字符串，求值不到类型。
0.10.0 的 ``dep()`` 持有类对象本身，不受影响。见 ``test_framework_boundaries.py``。
"""

from __future__ import annotations

from canary_framework import Canary, dep


class Provider(Canary):
    value = "ok"


class Consumer(Canary):
    provider = dep(Provider)

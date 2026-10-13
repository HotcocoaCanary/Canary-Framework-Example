"""The two HTTP layers, and how to pick one.

同一份业务，两层 HTTP：

* ``pipeline/http/fastapi.py`` —— 一个**原生 FastAPI 应用**，由我们的 ``Server`` 服务；
* ``pipeline/http/canary.py`` —— 路由与应用都是单元（``canary_framework.web.asgi.app``）。

这条流水线上 HTTP 只是**接入口**：队列、消费者、账本、闸门、停机的两个阶段都在业务那一侧
（``queue.py`` / ``workers.py`` / ``lanes.py`` / ``phases.py`` / ``app.py``），两层共用。
所以这两个文件各只有两个路由单元加一个应用单元。

每层各自给出 ``IngestServer`` 与 ``Pipeline``——``dep()`` 是写在类上的声明，图是静态的，
所以"服务哪个应用"只能由类决定。
"""

from __future__ import annotations

from types import ModuleType

from canary_framework import Canary

from pipeline.http import canary as canary_stack
from pipeline.http import fastapi as fastapi_stack

#: 栈名 -> 实现它的模块。每个模块都给出 ``IngestServer`` / ``Pipeline``。
STACKS: dict[str, ModuleType] = {"canary": canary_stack, "fastapi": fastapi_stack}

#: 两个栈的名字，测试用它参数化。
NAMES = tuple(STACKS)


def stack(name: str) -> ModuleType:
    """Return the module implementing *name*.

    :raises KeyError: 没有这个栈。
    """
    if name not in STACKS:
        raise KeyError(f"unknown stack {name!r}: pick one of {', '.join(NAMES)}")
    return STACKS[name]


def root(name: str) -> type[Canary]:
    """The root unit of *name* —— 它拥有那两个自定义阶段。"""
    return stack(name).Pipeline  # type: ignore[no-any-return]

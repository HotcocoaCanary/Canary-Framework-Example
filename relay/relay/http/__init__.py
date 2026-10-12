"""The two HTTP layers, and how to pick one.

同一份业务，两层 HTTP：

* ``relay/http/fastapi.py`` —— ``canary_framework.asgi.fastapi``，带 OpenAPI 与 ``/docs``；
* ``relay/http/web.py`` —— ``canary_framework.asgi.web``，只依赖 pydantic。

两层共用的东西比不共用的多得多：设备台账（``fleet.py``）、计数（``counters.py``）、
两份配置（``settings.py``）、巡检循环（``reaper.py``）、请求模型（``schema.py``），
以及**两个手写 ASGI 的应用单元**——``/metrics`` 与 ``/ws/events`` 跟 Web 框架无关，
所以两层直接共用同一份（``metrics.py`` / ``events.py``）。管理口的口令中间件也是共用的
（``plain.guard``），它只是一个 ASGI 中间件。

每层各自给出 ``PublicApi`` / ``AdminApp`` 两个应用单元，以及监听它们的
``PublicServer`` / ``AdminServer`` 与根单元 ``Relay``——``dep()`` 是写在类上的声明，
图是静态的，所以"听哪个应用"只能由类决定，不能在运行期挑。
"""

from __future__ import annotations

from types import ModuleType

from canary_framework import Canary

from relay.http import fastapi as fastapi_stack
from relay.http import web as web_stack

#: 栈名 -> 实现它的模块。每个模块都给出 ``PublicApi`` / ``AdminApp`` / ``Relay``。
STACKS: dict[str, ModuleType] = {"fastapi": fastapi_stack, "web": web_stack}

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
    """The root unit of *name* —— 两个端口、四个应用的那张图。"""
    return stack(name).Relay  # type: ignore[no-any-return]

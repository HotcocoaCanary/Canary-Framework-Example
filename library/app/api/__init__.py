"""The two HTTP layers, and how to pick one.

同一份业务，两层 HTTP：

* ``app/api/fastapi/`` —— ``canary_framework.asgi.fastapi``，带 OpenAPI 与 ``/docs``；
* ``app/api/web/`` —— ``canary_framework.asgi.web``，只依赖 pydantic。

业务代码（``app/module/*/service.py``、``app/module/db/``、``app/infra/``、``config.py``）
只有一份，两边都不碰。两边对外的路径、状态码、响应体一致，所以 ``tests/`` 里同一套行为
测试对两个栈各跑一遍。

**为什么是"取一个类"而不是"传一个参数"。** ``dep()`` 是写在类上的声明，图是静态的——
"听哪个应用"因此不能在运行期挑，只能由类决定。于是每个栈各有一个 ``LibraryApi`` 与一个
``Gateway``，这里只是按名字把它们取出来::

    python main.py --stack web --port 8011
"""

from __future__ import annotations

from types import ModuleType

from canary_framework import asgi

from app.api import fastapi as fastapi_stack
from app.api import web as web_stack

#: 栈名 -> 实现它的模块。每个模块都给出 ``LibraryApi`` 与 ``Gateway``。
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


def application(name: str) -> type[asgi.App]:
    """The application unit of *name* —— ``running(application("web"))`` 即启动那一层。"""
    return stack(name).LibraryApi  # type: ignore[no-any-return]


def gateway(name: str) -> type[asgi.Server]:
    """The listening unit of *name*."""
    return stack(name).Gateway  # type: ignore[no-any-return]

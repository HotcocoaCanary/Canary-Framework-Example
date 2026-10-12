"""The two HTTP layers, and how to pick one.

同一份业务，两层 HTTP。这一轮两层对比的是**两种写法**，而不是"两个我们自己的包"：

* ``app/api/canary/`` —— 路由与应用都是单元（``canary_framework.web.asgi.app``）。应用单元
  自己就是一个 ASGI 应用。
* ``app/api/fastapi/`` —— 一个**原生 FastAPI 应用**：模块级 ``APIRouter`` + ``Depends``，
  外加一座按类型取单元的桥。它由我们的 ``Server`` 服务（``self.app = fastapi_app``）。

业务代码（``app/module/*/service.py``、``app/module/db/``、``app/infra/``、``config.py``）
只有一份，两边都不碰。两边对外的路径、状态码、响应体一致，所以 ``tests/`` 里同一套行为
测试对两层各跑一遍。

ASGI 的意义就是两边各自守协议即可任意组合，所以这个项目里三种组合都有：

============================  ====================================================
我们的 app + 我们的 Server     ``python main.py --stack canary``
我们的 app + 原生 uvicorn      ``uvicorn asgi:app``（见 ``asgi.py``）
原生 FastAPI + 我们的 Server   ``python main.py --stack fastapi``
============================  ====================================================

**为什么是"取一个类"而不是"传一个参数"。** ``dep()`` 是写在类上的声明，图是静态的——
"服务哪个应用"因此不能在运行期挑，只能由类决定。于是每层各有一个 ``Gateway``，这里只是
按名字把它们取出来。
"""

from __future__ import annotations

from types import ModuleType

from canary_framework import Canary
from canary_framework.web.asgi.server import Server

from app.api import canary as canary_stack
from app.api import fastapi as fastapi_stack

#: 栈名 -> 实现它的模块。
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


def root_unit(name: str) -> type[Canary]:
    """The unit that is the root of this layer's graph.

    这一层的图从哪个单元启动：路由单元那边是应用单元自己，原生 FastAPI 那边是 ``Services``
    这个组合根——它没有应用单元，总得有人知道该启动谁。
    """
    module = stack(name)
    return module.LibraryApi if name == "canary" else module.Services  # type: ignore[no-any-return]


def gateway(name: str) -> type[Server]:
    """The listening unit of *name*."""
    return stack(name).Gateway  # type: ignore[no-any-return]

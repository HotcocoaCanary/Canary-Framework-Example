"""Two ports, four applications, one graph —— the parts both HTTP layers share.

这个文件是本场景的结构骨架，而且**与用哪个 Web 包无关**：

```
Relay                        根单元，自己不监听任何东西
├─ PublicServer   :8020      依赖即服务 —— 几个 ASGI 应用按 path 分发
│  ├─ PublicApi      /          HTTP API（canary 层是应用单元，fastapi 层是 FastAPI 对象）
│  ├─ EventStream    /ws/events  普通单元 + __call__（两层共用）
│  └─ Metrics        /metrics    普通单元 + __call__（两层共用）      ←┐
├─ AdminServer    :9020      手动拼装 —— @init 里给 self.app 赋值      │ 同一个实例
│  ├─ AdminApp       /admin     管理 API（同样由层决定）               │
│  ├─ Metrics        /metrics   ────────────────────────────────────────┘
│  └─ ready()        /          一个连单元都不是的 ASGI 函数
└─ Reaper                    后台巡检循环
```

**只有"哪个应用"是栈相关的**，所以这里把三个装配单元写成基类，各留一个类型注解，由
``relay/http/fastapi.py`` 与 ``relay/http/web.py`` 各给出那一条 ``dep()``。

基类里不写 ``api = dep(...)`` 的默认值，是因为这里没有一个合理的默认：两层是并列的，而且
``relay.server`` 写死任一层都会和 ``relay.http.*`` 形成循环导入。子类覆盖一条依赖本身是
支持的（依赖和钩子一样按属性名解析），``shop/warehouse.py`` 与 ``pipeline/workers.py`` 用的
就是那种写法。

四件事在这里成立：

**``Server`` 不是根单元。** 守护进程顺带开两个端口，就是根上两条 ``dep()``。回收顺序因此
是对的：两个 ``Server`` 先停（不再接新连接、等在途请求结束），之后才轮到它们依赖的应用、
再之后是 ``Fleet``。

**同一个应用单元被两个 ``Server`` 依赖。** ``Metrics`` 在两个端口上都应答，但图上只有一个
实例，两个端口读到的是同一份计数。它只是个带 ``__call__`` 的普通单元——服务器只认协议。

**两种给法都用了一次。** 对外端口（canary 层）用"依赖即服务"：直接依赖的几个可调用单元
各自应答自己的 ``path``（没有 ``path`` 属性的应答 ``/``）。管理端口两层都在 ``@init`` 里
给 ``self.app`` 赋值（见 ``assemble``），于是依赖的应用单元**不再自动加入**——``Metrics``
必须自己写进 ``dispatch`` 的表里，忘了就是"依赖了却没被服务"，而且不会报错。原生 FastAPI
那一层的对外端口也只能这么拼：一个端口上既有 FastAPI 应用，又有两个手写的可调用单元。

**端口与 uvicorn 的参数。** ``host`` / ``port`` 是普通类属性，所以 ``@init`` 里从
``Settings`` 赋值即可；``access_log=False`` 是类参数，原样传给 ``uvicorn.Config``——
压测时访问日志会严重干扰结果。
"""

from __future__ import annotations

from typing import Any

from canary_framework import Canary, dep, init
from canary_framework.web.asgi import Application, dispatch
from canary_framework.web.asgi.server import Server

from relay.counters import Counters
from relay.events import EventStream
from relay.fleet import Fleet
from relay.metrics import Metrics
from relay.plain import Receive, Scope, Send, reject, respond
from relay.reaper import Reaper
from relay.settings import AdminSettings, EdgeSettings


async def ready(scope: Scope, receive: Receive, send: Send) -> None:
    """``/`` on the admin port —— an ASGI application that is not a unit at all.

    管理端口的根：一个最小的 ASGI 函数，用来说明 ``dispatch`` 的表里放什么都行。
    """
    if scope["type"] != "http":
        await reject(send, scope)
        return
    if scope["path"] != "/":
        await respond(send, 404, "not found")
        return
    await respond(send, 200, "ready\n")


class PublicServer(Server, access_log=False):
    """The store-facing port: HTTP + WebSocket + metrics, dispatched by path.

    对外端口。``api`` 由各栈的子类给出。
    """

    config = dep(EdgeSettings)
    stream = dep(EventStream)
    metrics = dep(Metrics)

    #: 这一层的 HTTP API，由子类用 ``dep(...)`` 给出（canary 层）或在 ``@init`` 里拼
    #: （fastapi 层，见 ``relay/http/fastapi.py``）。
    api: Any

    @init
    def configure(self) -> None:
        self.host = self.config.host
        self.port = self.config.port


class AdminServer(Server, access_log=False):
    """The internal port, assembled by hand.

    管理端口，手动拼装。``console`` 由各栈的子类给出。
    """

    config = dep(AdminSettings)
    metrics = dep(Metrics)

    @init
    def configure(self) -> None:
        self.host = self.config.host
        self.port = self.config.port

    def assemble(self, console: Application, path: str = "/admin") -> Application:
        """The table this port serves: the admin application, metrics, and a bare ``/``.

        两层各自在 ``@init`` 里调它：``self.app = self.assemble(...)``。赋了 ``self.app``
        就以它为准——依赖的应用单元不再自动加入，所以 ``Metrics`` 必须写在这张表里，忘了
        就是"依赖了却没被服务"，而且不会报错。
        """
        return dispatch({path: console, self.metrics.path: self.metrics, "/": ready})


class Relay(Canary):
    """The root: two ports and a sweep loop.

    根单元：两个端口加一个巡检循环。它自己不监听任何东西。``public`` / ``admin`` 由各栈
    的子类给出。
    """

    reaper = dep(Reaper)
    fleet = dep(Fleet)
    counters = dep(Counters)

    #: 两个监听的单元，由子类用 ``dep(...)`` 给出。
    public: PublicServer
    admin: AdminServer

    def status(self) -> dict[str, object]:
        """A snapshot for the operator —— 进程里现在是什么样。"""
        return {
            "stack": type(self).__module__.rsplit(".", 1)[-1],
            "public": f"http://{self.public.host}:{self.public.port}",
            "admin": f"http://{self.admin.host}:{self.admin.port}",
            "devices": self.fleet.summary(),
            "sweeps": self.reaper.sweeps,
            "counters": self.counters.snapshot(),
        }

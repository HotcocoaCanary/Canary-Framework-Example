"""Two ports, four applications, one graph —— the parts both HTTP layers share.

这个文件是本场景的结构骨架，而且**与用哪个 Web 包无关**：

```
Relay                        根单元，自己不监听任何东西
├─ PublicServer   :8020      依赖即服务 —— 三个应用单元按 path 分发
│  ├─ PublicApi      /          HTTP API（这一层由栈决定：fastapi 或 web）
│  ├─ EventStream    /ws/events  手写的 WebSocket 应用（两层共用）
│  └─ Metrics        /metrics    手写的 Prometheus 应用（两层共用）←┐
├─ AdminServer    :9020      手动拼装 —— @init 里给 self.app 赋值      │ 同一个实例
│  ├─ AdminApp       /admin     管理 API（同样由栈决定）               │
│  ├─ Metrics        /metrics   ────────────────────────────────────────┘
│  └─ ready()        /          一个连单元都不是的 ASGI 函数
└─ Reaper                    后台巡检循环
```

**只有"哪个应用"是栈相关的**，所以这里把三个装配单元写成基类，各留一个类型注解，由
``relay/http/fastapi.py`` 与 ``relay/http/web.py`` 各给出那一条 ``dep()``。

基类里**不写** ``api = dep(...)`` 的默认值：依赖是按类型收集的，不像钩子那样按属性名
覆盖，基类写了那条边就也成立（``pipeline`` 场景里有最小复现）。

四件事在这里成立：

**``Server`` 不是根单元。** 守护进程顺带开两个端口，就是根上两条 ``dep()``。回收顺序因此
是对的：两个 ``Server`` 先停（不再接新连接、等在途请求结束），之后才轮到它们依赖的应用、
再之后是 ``Fleet``。

**同一个应用单元被两个 ``Server`` 依赖。** ``Metrics`` 在两个端口上都应答，但图上只有一个
实例，两个端口读到的是同一份计数。

**两种给法都用了一次。** 对外端口用"依赖即服务"：三个应用单元各自应答自己的 ``path``。
管理端口在 ``@init`` 里给 ``self.app`` 赋值，于是依赖的应用单元**不再自动加入**——
``Metrics`` 必须自己写进 ``dispatch`` 的表里，忘了就是"依赖了却没被服务"，而且不会报错。

**端口与 uvicorn 的参数。** ``host`` / ``port`` 是普通类属性，所以 ``@init`` 里从
``Settings`` 赋值即可；``access_log=False`` 是类参数，原样传给 ``uvicorn.Config``——
压测时访问日志会严重干扰结果。
"""

from __future__ import annotations

from canary_framework import Canary, asgi, dep, init

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


class PublicServer(asgi.Server, access_log=False):
    """The store-facing port: HTTP + WebSocket + metrics, dispatched by path.

    对外端口。``api`` 由各栈的子类给出。
    """

    config = dep(EdgeSettings)
    stream = dep(EventStream)
    metrics = dep(Metrics)

    #: 这一层的 HTTP API，由子类用 ``dep(...)`` 给出。
    api: asgi.App

    @init
    def configure(self) -> None:
        self.host = self.config.host
        self.port = self.config.port


class AdminServer(asgi.Server, access_log=False):
    """The internal port, assembled by hand.

    管理端口，手动拼装。``console`` 由各栈的子类给出。
    """

    config = dep(AdminSettings)
    metrics = dep(Metrics)

    #: 这一层的管理 API，由子类用 ``dep(...)`` 给出。
    console: asgi.App

    @init
    def configure(self) -> None:
        self.host = self.config.host
        self.port = self.config.port
        # 赋了 self.app 就以它为准：依赖的应用单元不再自动加入，表由自己写。
        self.app = asgi.dispatch(
            {
                self.console.path: self.console.app,
                self.metrics.path: self.metrics.app,
                "/": ready,
            }
        )


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

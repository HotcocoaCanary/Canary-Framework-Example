"""``/metrics`` —— an ASGI application that is just a unit with ``__call__``.

一个最朴素的应用单元：**普通的 ``Canary``，加一个 ``async def __call__(scope, receive,
send)``**。不继承任何东西——服务器单元只认 ASGI 协议，谁可调用谁就是应用。Prometheus 的
文本格式自己写最省事，连 pydantic 都用不上。

因为它不属于任何 web 框架，**两层 HTTP 直接共用这一份**。

这个单元被**两个** ``Server`` 依赖（对外端口与管理端口），但图上只有一个实例：所以两个
端口上读到的是同一份计数。

``path = "/metrics"`` 是给服务器看的：它决定这个单元在哪个前缀下被调用（没有这个属性就是
``/``）。``dispatch`` 不改写路径，所以应用自己看到的仍然是 ``/metrics``，下面的判断也要
照着写。
"""

from __future__ import annotations

from canary_framework import Canary, dep

from relay.counters import Counters
from relay.fleet import Fleet
from relay.plain import Receive, Scope, Send, reject, respond
from relay.settings import EdgeSettings


class Metrics(Canary):
    """The Prometheus text exposition of this process.

    本进程的 Prometheus 文本输出。
    """

    config = dep(EdgeSettings)
    counters = dep(Counters)
    fleet = dep(Fleet)

    #: 服务器按这个前缀分发到本单元。
    path = "/metrics"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != self.path:
            await reject(send, scope)
            return
        await respond(send, 200, self.render(), content_type="text/plain; version=0.0.4")

    def render(self) -> str:
        site = self.config.site_id
        lines = [
            "# HELP relay_up 1 if the relay is serving.",
            "# TYPE relay_up gauge",
            f'relay_up{{site="{site}"}} 1',
        ]
        for name, value in sorted(self.counters.snapshot().items()):
            lines += [f"# TYPE {name} counter", f'{name}{{site="{site}"}} {value}']
        lines += ["# HELP relay_devices Devices by status.", "# TYPE relay_devices gauge"]
        for status, count in sorted(self.fleet.summary().items()):
            lines.append(f'relay_devices{{site="{site}",status="{status}"}} {count}')
        return "\n".join(lines) + "\n"

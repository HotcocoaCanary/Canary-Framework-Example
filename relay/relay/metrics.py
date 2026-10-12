"""``/metrics`` —— an application unit that is not a FastAPI app.

一个不是 FastAPI 的应用单元：Prometheus 的文本格式自己写最省事，也正好说明
``asgi.App`` 对"应用"没有要求。

这个单元被**两个** ``Server`` 依赖（对外端口与管理端口），但图上只有一个实例：所以两个
端口上读到的是同一份计数。这是 ``asgi`` 文档里那句"同一个应用单元可以被两个 Server 依赖"
的实际样子。

``path = "/metrics"`` 只决定它在**哪个前缀下**被调用；``dispatch`` 不改写路径，所以应用自己
看到的仍然是 ``/metrics``，下面的判断也要照着写。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.asgi import App

from relay.counters import Counters
from relay.fleet import Fleet
from relay.plain import Receive, Scope, Send, reject, respond
from relay.settings import EdgeSettings


class Metrics(App):
    """The Prometheus text exposition of this process.

    本进程的 Prometheus 文本输出。
    """

    config = dep(EdgeSettings)
    counters = dep(Counters)
    fleet = dep(Fleet)

    path = "/metrics"

    @init
    def build(self) -> None:
        # 绑定方法就是一个合法的 ASGI 应用。
        self.app = self.serve

    async def serve(self, scope: Scope, receive: Receive, send: Send) -> None:
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

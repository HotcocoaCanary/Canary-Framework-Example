"""The whole process: one port, two lanes, two-step shutdown.

整个进程。结构：

```
Pipeline                    根单元，它拥有那两个自定义阶段
├─ IngestServer   :8030     HTTP 接入
│  └─ IngestApp      /          FastAPI 应用
│     ├─ BatchApi    /batches   提交进来就入队，不等做完
│     └─ StatusApi   /status    队列深度、在途、停机日志、给 LB 的 503
├─ FastLane                 小批量通道：N 个消费者 + FastQueue
├─ BulkLane                 大批量通道：M 个消费者 + BulkQueue
└─ Gate · JobBook · Ledger · Journal · PipelineSettings
```

**启动** 是三步：``init`` → ``start`` → ``serving``。前两步是框架的；第三步是这里加的，
它需要"全图都起来了"这个位置——消费者的 ``@start`` 只是把任务起出来，而"对外开始接活"
得等接入口也就绪。

**停机** 是三步，顺序正好反过来：``quiesce`` → ``stop``。
``leave(self, serving)`` 本单元在前，所以根单元的 ``@quiesce`` 先跑（关闸、``/health``
变 503），之后才轮到两条通道的 ``@quiesce``（排空在途），最后 ``super().stop()`` 才真正
回收（关监听、收消费者、清队列）。

反过来写不行：如果"关闸"是一个 ``after=start`` 的 ``enter``，顺序会变成依赖在前——
队列先关、消费者后知道、接入口最后知道，而接入口是最该先关的那个。两个方向都需要，
正是为什么框架给了 ``enter`` / ``leave`` 两条规则，而不是只有一条。
"""

from __future__ import annotations

import logging

from canary_framework import Canary, asgi, dep, enter, init, leave

from pipeline.gate import Gate
from pipeline.jobs import JobBook
from pipeline.journal import Journal
from pipeline.lanes import BulkLane, FastLane
from pipeline.ledger import Ledger
from pipeline.phases import quiesce, serving
from pipeline.settings import PipelineSettings

logger = logging.getLogger("pipeline")


class IngestServer(asgi.Server, access_log=False):
    """The one port this process listens on.

    唯一的端口。``api`` 由各栈的子类给出（见 ``pipeline/http/``）——``dep()`` 是写在类上的
    声明，所以"听哪一层"只能由类决定。基类里不写它的默认值：依赖按类型收集，不像钩子那样
    按属性名覆盖，基类写了那条边就也成立。

    ``access_log=False`` 是类参数，原样传给 ``uvicorn.Config``——压测时访问日志会严重干扰
    结果。
    """

    config = dep(PipelineSettings)

    #: 这一层的接入应用，由子类用 ``dep(...)`` 给出。
    api: asgi.App

    @init
    def configure(self) -> None:
        self.host = self.config.host
        self.port = self.config.port


class Pipeline(Canary):
    """The root —— it owns the two extra phases.

    根单元：两个自定义阶段由它推进。``server`` 由各栈的子类给出。
    """

    config = dep(PipelineSettings)
    fast = dep(FastLane)
    bulk = dep(BulkLane)
    gate = dep(Gate)
    book = dep(JobBook)
    ledger = dep(Ledger)
    journal = dep(Journal)

    #: 监听的单元，由子类用 ``dep(...)`` 给出。
    server: IngestServer

    async def start(self) -> None:
        """Run the graph's ``@start``, then open the intake.

        覆盖生命周期方法是框架明确支持的写法：``async with Pipeline()`` 与
        ``pipeline.start()`` 两种入口都自动带上 ``serving``，调用者不必记得多调一步。
        """
        await super().start()
        await enter(self, serving)

    async def stop(self) -> None:
        """Close the intake and drain, then reclaim the graph.

        先离开 ``serving``（本单元在前：关闸 → 排空），再回收。``leave`` 不会动 ``start``
        ——``start`` 是 ``serving`` 的前驱而不是后继——所以这之后整张图仍然是启动着的，
        ``super().stop()`` 照常把 ``@stop`` 跑完。

        重复调用是安全的：``serving`` 已经离开过就成了空操作。
        """
        await leave(self, serving)
        await super().stop()

    @serving
    async def opened(self) -> None:
        self.journal.note("serving: 接入开放")

    @quiesce
    async def close_the_gate(self) -> None:
        """Step one of shutdown: stop taking new work. Nothing is reclaimed yet.

        停机第一步：不再接新活。``/status/health`` 从此回 503，而端口还在监听，在途请求
        照常做完——上游有时间把流量摘走。
        """
        self.gate.close()
        self.fast.queue.close()
        self.bulk.queue.close()
        self.journal.note("quiesce: 关闸（/status/health 开始回 503）")

    def status(self) -> dict[str, object]:
        return {
            "listening": f"http://{self.server.host}:{self.server.port}",
            "accepting": self.gate.accepting,
            "lanes": {
                lane.lane: {"queued": lane.queue.depth, "in_flight": len(lane.in_flight), "done": lane.done}
                for lane in (self.fast, self.bulk)
            },
            "jobs": self.book.states(),
            "ledger": self.ledger.summary(),
        }

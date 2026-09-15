"""The composition root — three units that turn the graph into a running daemon.

``CollectorDaemon`` 与 ``AlertDaemon`` 各管一段管线，各自把周期作业注册给调度器；
``TelemetryDaemon`` 依赖两者，并负责把 ``@launch`` 阶段推起来。

**根单元为什么还要覆盖 start()。** 推进沿依赖向下，依赖的 ``@start`` 一定早于依赖者，
所以没有任何单元的 ``@start`` 能站在"全图都起来了"这个位置上。0.10.0 的答案是加一个
阶段（``telemetry/phases.py``），而推进这个阶段的动作要有人做——生命周期方法本身可以
覆盖，于是根单元把它接在 ``start()`` 后面::

    async def start(self) -> None:
        await super().start()        # 全图 @start
        await advance(self, launch)  # 再广播 @launch

这样 ``async with TelemetryDaemon()`` 和 ``daemon.start()`` 两种写法都自动带上
``@launch``，调用者不必记得多调一步。

每个 daemon 还各自暴露一个 ``*_once()`` 协程：调度器调它，测试也直接调它——
时间驱动的系统只有在能被手动推进时才谈得上可测。
"""

from __future__ import annotations

import logging

from canary_framework import Canary, advance, dep, start

from telemetry.domain.models import Alert
from telemetry.infra.clock import Clock
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.phases import launch
from telemetry.pipeline.aggregator import WindowAggregator
from telemetry.pipeline.dispatcher import AlertDispatcher
from telemetry.pipeline.rules import RuleEngine
from telemetry.settings import AppConfig
from telemetry.source.sample_source import SampleSource
from telemetry.store.device_registry import DeviceRegistry
from telemetry.store.metric_store import MetricStore

logger = logging.getLogger("telemetry.daemon")


class CollectorDaemon(Canary):
    """Stage 1 — poll the source and write into the store."""

    config = dep(AppConfig)
    scheduler = dep(Scheduler)
    source = dep(SampleSource)
    store = dep(MetricStore)

    collected: int = 0

    @start
    async def register(self) -> None:
        # 注册在 @start，开跑在 @launch —— 见 infra/scheduler.py。
        self.scheduler.every("collect", self.config.collect_interval_seconds, self.collect_once)

    async def collect_once(self) -> None:
        samples = await self.source.read()
        self.collected += self.store.record_many(samples)


class AlertDaemon(Canary):
    """Stage 2 — aggregate, evaluate rules, dispatch what survives cooldown."""

    config = dep(AppConfig)
    scheduler = dep(Scheduler)
    aggregator = dep(WindowAggregator)
    rules = dep(RuleEngine)
    dispatcher = dep(AlertDispatcher)
    devices = dep(DeviceRegistry)

    evaluations: int = 0

    @start
    async def register(self) -> None:
        self.scheduler.every("evaluate", self.config.evaluate_interval_seconds, self.evaluate_once)

    async def evaluate_once(self) -> list[Alert]:
        stats = self.aggregator.current()
        alerts = self.rules.evaluate(stats)
        sent = await self.dispatcher.dispatch(alerts)
        self.evaluations += 1
        return sent


class TelemetryDaemon(Canary):
    """The root — it owns the extra phase that starts the background loops."""

    collector = dep(CollectorDaemon)
    alerts = dep(AlertDaemon)
    scheduler = dep(Scheduler)
    tasks = dep(SupervisedTasks)
    clock = dep(Clock)

    async def start(self) -> None:
        """Run the graph's ``@start``, then broadcast ``@launch``.

        覆盖生命周期方法是 0.10.0 明确支持的写法：钩子按属性名解析，``super()`` 组合。
        """
        await super().start()
        await advance(self, launch)

    @launch
    async def announce(self) -> None:
        logger.info("遥测守护进程已启动，作业: %s", ", ".join(self.scheduler.jobs) or "（无）")

    def status(self) -> dict[str, object]:
        """A snapshot for the operator — what a health endpoint would return."""
        return {
            "jobs": {
                name: {
                    "interval": stats.interval,
                    "ticks": stats.ticks,
                    "failures": stats.failures,
                    "last_error": stats.last_error,
                }
                for name, stats in self.scheduler.jobs.items()
            },
            "running_tasks": self.tasks.running,
            "task_failures": [name for name, _ in self.tasks.failures],
            "collected_samples": self.collector.collected,
            "evaluations": self.alerts.evaluations,
            "alerts": self.alerts.dispatcher.stats,
        }

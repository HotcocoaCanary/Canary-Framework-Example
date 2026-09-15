"""The composition root — three units that turn the graph into a running daemon.

``CollectorDaemon`` and ``AlertDaemon`` each own one stage of the pipeline and
register their periodic job with the scheduler.  ``TelemetryDaemon`` depends on
both and starts the loops.

Why the split matters: Canary runs ``@on_start`` in topological order, so a
dependency's hook fires *before* its dependents'.  A unit therefore cannot launch
work that touches its dependents.  The root is the only place guaranteed to run
after everything else — see ``Scheduler.start_all``.

Each daemon also exposes a ``*_once()`` coroutine.  That is what the scheduler
calls, and it is what the tests call directly: a time-driven system is only
testable if you can advance it by hand instead of sleeping.
"""

from __future__ import annotations

import logging

from telemetry.domain.models import Alert
from telemetry.infra.clock import Clock
from telemetry.infra.scheduler import Scheduler
from telemetry.infra.tasks import SupervisedTasks
from telemetry.pipeline.aggregator import WindowAggregator
from telemetry.pipeline.dispatcher import AlertDispatcher
from telemetry.pipeline.rules import RuleEngine
from telemetry.source.sample_source import SampleSource
from telemetry.store.device_registry import DeviceRegistry
from telemetry.store.metric_store import MetricStore
from canary_framework import cocoa, on_start
from telemetry.settings import AppConfig

logger = logging.getLogger("telemetry.daemon")


@cocoa(deps=[AppConfig, Scheduler, SampleSource, MetricStore])
class CollectorDaemon:
    """Stage 1 — poll the source and write into the store."""

    app_config: AppConfig
    scheduler: Scheduler
    sample_source: SampleSource
    metric_store: MetricStore

    collected: int = 0

    @on_start
    async def register(self) -> None:
        self.scheduler.every(
            "collect", self.app_config.collect_interval_seconds, self.collect_once
        )

    async def collect_once(self) -> None:
        samples = await self.sample_source.read()
        self.collected += self.metric_store.record_many(samples)


@cocoa(
    deps=[
        AppConfig,
        Scheduler,
        WindowAggregator,
        RuleEngine,
        AlertDispatcher,
        DeviceRegistry,
    ]
)
class AlertDaemon:
    """Stage 2 — aggregate, evaluate rules, dispatch what survives cooldown."""

    app_config: AppConfig
    scheduler: Scheduler
    window_aggregator: WindowAggregator
    rule_engine: RuleEngine
    alert_dispatcher: AlertDispatcher
    device_registry: DeviceRegistry

    evaluations: int = 0

    @on_start
    async def register(self) -> None:
        self.scheduler.every(
            "evaluate", self.app_config.evaluate_interval_seconds, self.evaluate_once
        )

    async def evaluate_once(self) -> list[Alert]:
        stats = self.window_aggregator.current()
        alerts = self.rule_engine.evaluate(stats)
        sent = await self.alert_dispatcher.dispatch(alerts)
        self.evaluations += 1
        return sent


@cocoa(deps=[CollectorDaemon, AlertDaemon, Scheduler, SupervisedTasks, Clock])
class TelemetryDaemon:
    """The root — the only unit guaranteed to start after all the others."""

    collector_daemon: CollectorDaemon
    alert_daemon: AlertDaemon
    scheduler: Scheduler
    supervised_tasks: SupervisedTasks
    clock: Clock

    @on_start
    async def launch(self) -> None:
        self.scheduler.start_all()
        logger.info(
            "遥测守护进程已启动，作业: %s", ", ".join(self.scheduler.jobs)
        )

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
            "running_tasks": self.supervised_tasks.running,
            "task_failures": [name for name, _ in self.supervised_tasks.failures],
            "collected_samples": self.collector_daemon.collected,
            "evaluations": self.alert_daemon.evaluations,
            "alerts": self.alert_daemon.alert_dispatcher.stats,
        }

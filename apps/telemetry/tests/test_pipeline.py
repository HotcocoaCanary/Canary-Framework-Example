"""The processing pipeline — aggregation, rules, and alert de-duplication."""

from __future__ import annotations

from telemetry.domain.models import Alert, AlertKind, Device, Sample, Severity, Threshold
from telemetry.pipeline.aggregator import WindowAggregator
from telemetry.pipeline.dispatcher import AlertDispatcher
from telemetry.daemon import TelemetryDaemon
from telemetry.infra.clock import Clock
from telemetry.pipeline.rules import RuleEngine
from telemetry.store.device_registry import DeviceRegistry
from telemetry.store.metric_store import MetricStore
from telemetry.testing import collect_for, started_runtime


# --- 存储 -------------------------------------------------------------


async def test_series_are_bounded():
    """A daemon runs for weeks — an unbounded buffer is a slow memory leak."""
    runtime, clock = await started_runtime(series_capacity=5)

    store = runtime[MetricStore]
    for index in range(20):
        store.record(Sample(device_id="d", metric="m", value=float(index), at=float(index)))

    kept = store.window("d", "m", since=0, until=100)
    assert len(kept) == 5
    assert [s.value for s in kept] == [15.0, 16.0, 17.0, 18.0, 19.0]
    await runtime.stop()


async def test_window_filters_by_time(daemon, clock):
    store = daemon.collector_daemon.metric_store
    for at in (10.0, 20.0, 30.0, 40.0):
        store.record(Sample(device_id="d", metric="m", value=at, at=at))

    assert [s.value for s in store.window("d", "m", since=20, until=30)] == [20.0, 30.0]
    assert store.latest("d", "m").value == 40.0
    assert store.last_seen("d") == 40.0


# --- 聚合 -------------------------------------------------------------


async def test_aggregate_reports_count_avg_and_extremes(daemon, clock, runtime):
    await collect_for(daemon, clock, seconds=20, step=2.0)
    stats = {(s.device_id, s.metric): s for s in runtime[WindowAggregator].current()}

    cpu = stats[("gateway-01", "cpu")]
    assert cpu.count == 10
    assert cpu.minimum <= cpu.avg <= cpu.maximum
    assert cpu.minimum <= cpu.p95 <= cpu.maximum


async def test_aggregate_skips_series_with_no_samples_in_window(daemon, clock, runtime):
    await collect_for(daemon, clock, seconds=10, step=2.0)
    clock.advance(1000)  # 把所有样本推出窗口
    assert runtime[WindowAggregator].current() == []


# --- 规则 -------------------------------------------------------------


async def test_threshold_rule_escalates_warning_to_critical(daemon, clock, runtime):
    source = daemon.collector_daemon.sample_source
    engine = runtime[RuleEngine]

    source.force("gateway-01", "cpu", 45.0)  # 窗口均值 ~97，越过 95 严重线
    await collect_for(daemon, clock, seconds=20, step=2.0)
    alerts = engine.evaluate(runtime[WindowAggregator].current())

    cpu = [a for a in alerts if a.metric == "cpu" and a.kind is AlertKind.THRESHOLD]
    assert len(cpu) == 1
    assert cpu[0].severity is Severity.CRITICAL
    assert "严重线" in cpu[0].message


async def test_the_default_fleet_is_quiet(daemon, clock, runtime):
    """A monitor whose seeded fleet alarms on day one trains operators to ignore it.

    Every seeded threshold sits above the synthetic baseline; this test is what
    keeps the two in sync when either is edited.
    """
    await collect_for(daemon, clock, seconds=20, step=2.0)
    alerts = runtime[RuleEngine].evaluate(runtime[WindowAggregator].current())
    assert alerts == []


async def test_rate_rule_catches_a_jump_that_is_still_below_the_threshold():
    """The rule that spots a failing fan *before* the threshold alarm fires.

    CPU goes 66.9 → 79.3 (+18.5%), which never reaches the warning line of 88.
    A threshold-only monitor stays silent here; the rate rule does not.
    """
    runtime, clock = await started_runtime(rate_change_ratio=0.15)
    await runtime[TelemetryDaemon].supervised_tasks.shutdown()
    daemon = runtime[TelemetryDaemon]
    engine = runtime[RuleEngine]
    source = daemon.collector_daemon.sample_source

    await collect_for(daemon, clock, seconds=20, step=2.0)
    engine.evaluate(runtime[WindowAggregator].current())  # 建立基线

    clock.advance(35)  # 推过窗口，避免两阶段样本混在一起稀释变化
    source.force("gateway-01", "cpu", 15.0)
    await collect_for(daemon, clock, seconds=20, step=2.0)
    alerts = engine.evaluate(runtime[WindowAggregator].current())

    rate = [a for a in alerts if a.kind is AlertKind.RATE and a.metric == "cpu"]
    assert rate, "CPU 阶跃上升应触发变化率告警"
    assert rate[0].severity is Severity.WARNING
    assert "上升" in rate[0].message
    # 关键：此时阈值规则仍然是沉默的
    assert [a for a in alerts if a.kind is AlertKind.THRESHOLD and a.metric == "cpu"] == []
    await runtime.stop()


async def test_offline_rule_fires_when_a_device_goes_quiet(daemon, clock, runtime):
    await collect_for(daemon, clock, seconds=10, step=2.0)
    clock.advance(120)  # 远超 offline_after_seconds

    alerts = runtime[RuleEngine].evaluate(runtime[WindowAggregator].current())
    offline = [a for a in alerts if a.kind is AlertKind.OFFLINE]
    assert len(offline) == 3  # 三台设备全部离线
    assert all(a.severity is Severity.CRITICAL for a in offline)
    assert "无数据上报" in offline[0].message


async def test_an_offline_device_produces_no_other_alerts(daemon, clock, runtime):
    """A silent device makes threshold and rate results meaningless."""
    source = daemon.collector_daemon.sample_source
    source.force("gateway-01", "cpu", 45.0)
    await collect_for(daemon, clock, seconds=20, step=2.0)
    clock.advance(120)

    alerts = runtime[RuleEngine].evaluate(runtime[WindowAggregator].current())
    assert {a.kind for a in alerts} == {AlertKind.OFFLINE}


async def test_a_device_without_thresholds_is_skipped(daemon, clock, runtime):
    registry: DeviceRegistry = runtime[DeviceRegistry]
    registry.add(Device(id="unmonitored", name="无规则设备", metrics=("noise",)))

    await collect_for(daemon, clock, seconds=20, step=2.0)
    alerts = runtime[RuleEngine].evaluate(runtime[WindowAggregator].current())
    assert [a for a in alerts if a.device_id == "unmonitored" and a.kind is AlertKind.THRESHOLD] == []


# --- 投递 -------------------------------------------------------------


def _alert(at: float, severity: Severity = Severity.WARNING) -> Alert:
    return Alert(
        device_id="d", metric="m", kind=AlertKind.THRESHOLD,
        severity=severity, value=1.0, message="x", at=at,
    )


async def test_repeat_alerts_are_suppressed_during_cooldown():
    runtime, clock = await started_runtime(alert_cooldown_seconds=100.0)
    dispatcher: AlertDispatcher = runtime[AlertDispatcher]

    assert len(await dispatcher.dispatch([_alert(0.0)])) == 1
    assert await dispatcher.dispatch([_alert(50.0)]) == []      # 冷却中
    assert len(await dispatcher.dispatch([_alert(150.0)])) == 1  # 冷却结束
    assert dispatcher.stats == {"delivered": 2, "suppressed": 1}
    await runtime.stop()


async def test_a_severity_change_is_not_suppressed():
    """Warning → critical must get through even inside the cooldown window."""
    runtime, clock = await started_runtime(alert_cooldown_seconds=1000.0)
    dispatcher: AlertDispatcher = runtime[AlertDispatcher]

    await dispatcher.dispatch([_alert(0.0, Severity.WARNING)])
    escalated = await dispatcher.dispatch([_alert(5.0, Severity.CRITICAL)])
    assert len(escalated) == 1
    assert escalated[0].severity is Severity.CRITICAL
    await runtime.stop()


async def test_history_is_bounded():
    runtime, clock = await started_runtime(alert_history_size=3, alert_cooldown_seconds=0.0)
    dispatcher: AlertDispatcher = runtime[AlertDispatcher]

    for at in range(10):
        await dispatcher.dispatch([_alert(float(at))])
    assert len(dispatcher.history) == 3
    await runtime.stop()

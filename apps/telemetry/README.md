# 场景二：设备遥测采集与告警

一个用 Canary Framework **0.9.3**（`release/0.9.3` @ `fb712de`）写的**常驻守护进程**：周期采集设备指标 → 滚动窗口聚合
→ 规则评估 → 告警去重投递。

与 [场景一](../library/README.md) 的对照是刻意的：那里是请求驱动的 HTTP API，
由 uvicorn 的 lifespan 驱动生命周期；这里没有 ASGI，进程用
`async with Canary(TelemetryDaemon)` 自己驱动，靠信号退出。
依赖里**没有** `canary-framework[web]`，用来验证框架「web 扩展延迟 import」的承诺。

## 运行

```bash
uv run python main.py     # Ctrl-C 优雅退出
uv run pytest             # 44 个测试，零外部依赖
```

```
2026-09-04 17:52:10 INFO  telemetry.daemon: 遥测守护进程已启动，作业: collect, evaluate
2026-09-08 17:49:37 INFO  telemetry: 装配完成，14 个单元：AppConfig → Clock →
  SupervisedTasks → LoggingAlertSink → DeviceRegistry → MetricStore → Scheduler →
  AlertDispatcher → SampleSource → WindowAggregator → RuleEngine → CollectorDaemon →
  AlertDaemon → TelemetryDaemon
```

`AppConfig` 排在最前面：配置在框架里没有特殊地位，就是图上一个普通的
`@cocoa` 节点，谁要用谁写进 `deps=[AppConfig]`。把 `CANARY_LOG_LEVEL=DEBUG` 打开
还能看到框架自己的装配摘要。

## 架构

```
main.py                    async with Canary(TelemetryDaemon) —— 无 ASGI，信号驱动
telemetry/
  settings.py              AppConfig（@cocoa + pydantic-settings，图上的普通节点）
  infra/
    clock.py               Clock / ManualClock       真实时钟 | 手动推进（测试用替身）
    tasks.py               SupervisedTasks 后台任务监管 ← 框架缺失，自建
    scheduler.py           Scheduler       周期作业驱动 ← 框架缺失，自建
  source/sample_source.py  SampleSource / HttpSampleSource  确定性波形 | 轮询 HTTP
  store/
    metric_store.py        MetricStore    每序列一个有界环形缓冲
    device_registry.py     DeviceRegistry 设备与阈值
  pipeline/
    aggregator.py          WindowAggregator  count/avg/min/max/p95
    rules.py               RuleEngine        离线 → 阈值 → 变化率
    dispatcher.py          AlertDispatcher   指纹去重 + 冷却（投递交给 sink）
    sink.py                LoggingAlertSink / WebhookAlertSink  写日志 | POST webhook
  daemon.py                CollectorDaemon / AlertDaemon / TelemetryDaemon(根)
```

### 三条值得说明的设计

**后台任务必须自己管。** `asyncio.create_task` 在守护进程里是不安全的：任务只被事件循环
弱引用（可能被 GC）、异常被吞掉、生命周期与应用无关。`SupervisedTasks` 补上这三点——
持强引用、记录失败、`@on_stop` 时取消并 await。框架没有任何任务设施
（`dir(Canary)` 只有 `init/start/stop/state/order/instances`），每个跑后台工作的
Canary 项目都得写一遍。

**调度器不能用自己的 `@on_start` 启动循环。** 钩子按拓扑序执行，依赖先于被依赖者，
所以调度器的钩子一定早于所有注册方——那时一个作业都没注册。真正启动循环的是**根**
`TelemetryDaemon`，因为 Kahn 算法保证传递依赖了整张图的根排在最后。这条性质可靠但
没有文档，见 [#013](../../../Canary-Framework/tmp/bug/013-startup-order-guarantees-undocumented.md)。

**规则顺序是有讲究的：离线 → 阈值 → 变化率。** 一台已经不上报的设备，它的阈值和变化率
都是无意义的历史数据，所以离线设备直接跳过后两条规则。变化率规则的价值在于
**在阈值报警之前**发现异常：CPU 从 66.9 涨到 79.3（+18.5%）从未触及 88 的警告线，
只有阈值规则的监控系统在这里是沉默的。

## 业务规则

- 采集间隔 1s，评估间隔 5s，窗口 30s（均可配）
- 阈值：窗口均值越过 warning / critical 线
- 变化率：相对上一窗口变化超过 `rate_change_ratio`（默认 50%）
- 离线：超过 `offline_after_seconds` 无任何指标上报
- 告警按 (设备, 指标, 类型, 级别) 指纹去重，冷却期内抑制；级别升级不受抑制
- 种子阈值全部留在合成基线之上——默认满屏告警的监控系统等于没有监控
  （`tests/test_pipeline.py::test_the_default_fleet_is_quiet` 守着这条）

## 测试

时间是被测试拥有的：全部管线测试一次 `sleep` 都不需要。框架没有替换入口
（`provide=` 在最终版被删掉了），所以这条缝由 `telemetry/testing.py` 自己搭——
注入发生在 `init()`，`@on_start` 还没跑，中间那一刻把注入好的 `Clock` 换成手动时钟。
六行，见 `swap_clock`。
只有 `tests/test_daemon.py` 用真实时钟跑几十毫秒，验证调度器循环真的会自己转起来
——一个只有测试手动调用才工作的调度器不是调度器。

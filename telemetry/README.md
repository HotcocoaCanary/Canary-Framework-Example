# 场景二：设备遥测采集与告警

一个用 [Canary Framework](https://pypi.org/project/canary-framework/) **1.1**
写的**常驻守护进程**：周期采集设备指标 → 滚动窗口聚合 → 规则评估 → 告警去重投递。

与 [场景一](../library/README.md) 的对照是刻意的：那里是请求驱动的 HTTP API，由 ASGI
的 lifespan 驱动生命周期；这里没有 ASGI，进程用 `async with TelemetryDaemon()` 自己
驱动，靠信号退出。框架的 `__aenter__` / `__aexit__` 正好覆盖这个用法。

依赖里**只有核心**：`canary-framework` 是纯标准库、零第三方依赖，本项目
除了 `pydantic-settings` 与 `httpx` 之外不装任何 web 相关的包
（`tests/test_lifecycle.py` 用子进程钉住了这条）。

## 运行

```bash
uv sync
uv run pytest             # 58 个测试，零外部依赖
uv run python main.py     # Ctrl-C 优雅退出
```

```
2026-09-15 11:41:43 INFO  telemetry.scheduler: 调度器已启动，作业: collect, evaluate
2026-09-15 11:41:43 INFO  telemetry.daemon:   遥测守护进程已启动，作业: collect, evaluate
2026-09-15 11:41:44 INFO  telemetry: 收到停止信号，最终状态：{'jobs': {'collect': {...}}, ...}
```

## 架构

```
main.py                    async with TelemetryDaemon() —— 无 ASGI，信号驱动
telemetry/
  settings.py              AppConfig（BaseSettings + Canary，图上的普通节点）
  phases.py                launch = Phase("launch", after=start)  ← 第四个阶段
  infra/
    clock.py               Clock / ManualClock       真实时钟 | 手动推进（测试替身）
    tasks.py               SupervisedTasks 后台任务监管 ← 框架不提供，自建
    scheduler.py           Scheduler       周期作业驱动   ← 框架不提供，自建
  source/sample_source.py  SampleSource    确定性波形 | 轮询 HTTP
  store/
    metric_store.py        MetricStore     每序列一个有界环形缓冲
    device_registry.py     DeviceRegistry  设备与阈值
  pipeline/
    aggregator.py          WindowAggregator  count/avg/min/max/p95
    rules.py               RuleEngine        离线 → 阈值 → 变化率
    dispatcher.py          AlertDispatcher   指纹去重 + 冷却（投递交给 sink）
    sink.py                LoggingAlertSink  写日志 | POST webhook
  daemon.py                CollectorDaemon / AlertDaemon / TelemetryDaemon(根)
```

### 四条值得说明的设计

**第四个阶段解决了"全图起来之后"。** 调度器必须等所有单元注册完作业才能开循环，
而 `@start` 给不了这个位置：推进沿依赖向下，依赖的 `@start` 一定早于依赖者，调度器
作为被依赖方反而最先跑。阶段是一等对象，三行就够：

```python
launch = Phase("launch", after=start)     # phases.py
```

各单元在 `@start` 里注册作业，调度器在 `@launch` 里统一开循环；`after=start` 是一道
栅栏，跳过 `start()` 直接推 `launch` 会抛 `LifecycleError`，而不是被静默跳过。
推进它的是根单元——生命周期方法本身可以覆盖：

```python
class TelemetryDaemon(Canary):
    async def start(self) -> None:
        await super().start()             # 全图 @start
        await enter(self, launch)         # 再广播 @launch
```

0.9.x 没有这个能力，同样的需求只能靠"根排在拓扑序最后"这条未写进文档的性质去绕。

**配置既是 pydantic 模型，又是图上的节点。** 单元就是普通 Python 类，所以两个基类
一起继承即可：`class AppConfig(BaseSettings, Canary)`。配置在框架里没有任何特殊地位。

**后台任务必须自己管。** `asyncio.create_task` 在守护进程里是不安全的：任务只被事件
循环弱引用（可能被 GC）、异常被吞掉、生命周期与应用无关。`SupervisedTasks` 补上这三点
——持强引用、记录失败、`@stop` 时取消并 await。框架的核心只做依赖注入与生命周期，
没有任务设施；但它给了一个站得住的挂载点：回收是唯一路径，正常结束与失败结束共用。

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

时间是被测试拥有的：全部管线测试一次 `sleep` 都不需要。做法是在生命周期开始前
`scope_of(daemon).provide(Clock, ManualClock())`，整张图就跑在手动时钟上，真 `Clock`
连构造都不会发生。见 `telemetry/testing.py`。

0.9.x 的 `setattr` 缝做不到这点：被替掉的那棵子树照样实例化、照样跑 `@on_start`
——换掉仓储也拦不住它的依赖去连数据库。

只有 `tests/test_daemon.py` 用真实时钟跑几十毫秒，验证调度器循环真的会自己转起来
——一个只有测试手动调用才工作的调度器不是调度器。

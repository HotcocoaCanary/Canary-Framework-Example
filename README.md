# canary-framework 多场景示例

用**形态刻意不同**的两个真实项目分别压测
[Canary Framework](https://pypi.org/project/canary-framework/) **0.10.0**，
收集单一场景看不到的框架能力与取舍。

```
library/     场景一：智能图书馆管理系统 + RAG —— 请求驱动的 HTTP API（Canary + FastAPI）
telemetry/   场景二：设备遥测采集与告警     —— 时间驱动的常驻守护进程（纯核心，零 web 依赖）
```

两个目录各自是一个**独立的 uv 工程**（自带 `pyproject.toml` 与 `uv.lock`），
拷出去或作为子模块挂到别的仓库里都能直接跑，互不依赖，也不依赖本仓库根目录。

## 快速开始

```bash
cd library    && uv sync && uv run pytest && uv run python main.py   # http://127.0.0.1:8010/docs
cd telemetry  && uv sync && uv run pytest && uv run python main.py   # 守护进程，Ctrl-C 优雅退出
```

两个项目默认都是**零外部依赖**的：library 用 SQLite 内存库 + 离线确定性模型，
telemetry 用合成波形 + 内存存储。接真实的 PostgreSQL/pgvector、LLM、HTTP 采集源
都只需改各自的 `.env`。

测试共 159 条：library 101 + telemetry 58。

## 0.10.0 之后，这两个示例长什么样

0.10.0 重写了核心，与 0.9.x 完全不兼容，也没有兼容层。对示例影响最大的三件事：

**`canary_framework.web` 没有了。** 框架的定位收回到「面向普通 Python 类的依赖注入与
生命周期」，不再兼管 HTTP。所以场景一的 web 那一半换成了 FastAPI，两者的接触面收敛到
一个文件 [`library/app/wiring.py`](library/app/wiring.py)，只有三件事：lifespan 对接、
按类型取单元、领域异常落地。分开之后每一侧都是该领域里最普通的写法。

**装饰器换成基类。** `@cocoa` 与 `Canary(*roots)` 容器都不存在了；继承 `Canary` 即为一个
单元，`dep(...)` 声明依赖，单元自己就能走完自己的一生。因此没有"组装根"那一层了——
`async with LibraryApi()` 或 `async with TelemetryDaemon()` 就是全部。

**阶段是一等对象。** `Phase("launch", after=start)` 直接就是第四个阶段，无需注册。
场景二拿它解决了一个 0.9.x 里只能靠拓扑巧合去凑的问题，见下。

## 为什么要两个场景

**缺陷的发现**需要多场景：场景一压的是请求路径上的东西（请求体失败路径、响应校验、
冷启动并发），却从头到尾触发不了一次生命周期失败——uvicorn 在 lifespan 启动失败时
直接杀进程，把问题掩盖了。换成守护进程形态，停止语义上的问题立刻现形。

**取舍的代价**也要两边一起看才清楚。两个例子：

*框架没有替换入口。* 图上的实例一律由框架无参构造，所以"用哪个实现"这件事回到单元
内部：[场景一](library/app/infra/ai.py)（本地还是远端模型）与
[场景二](telemetry/telemetry/source/sample_source.py)（合成波形还是 HTTP 采集）
长出了同一形状的配置分支。一边看像是接线风格，两边一起看才是框架的取舍。

*但测试的替换缝变好了。* 0.10.0 里 `Scope.instances` 就是"类型 → 实例"那张表，而
`dep(...)` 读的正是它——在生命周期开始前把替身放进去，整张图就拿到替身，**真单元连构造
都不会发生**。0.9.x 的 `setattr` 缝做不到这点：被替掉的那棵子树照样实例化、照样启动。
两个场景各有一个六行的 `seed()`（[库](library/app/testing.py)、
[遥测](telemetry/telemetry/testing.py)）。

*第四个阶段值不值。* 守护进程需要一个"全图都起来之后"的位置——调度器要等所有单元注册完
作业才能开循环。`@start` 给不了：推进沿依赖向下，调度器作为被依赖方反而最先跑。0.9.x 里
只能靠"根排在拓扑序最后"这条未文档化的性质去绕；0.10.0 里
[三行声明一个 `@launch` 阶段](telemetry/telemetry/phases.py)就解决了，`after=start`
还顺带保证阶段不会被静默跳过。场景一完全用不到这个能力——它的"全图起来之后"由 ASGI
lifespan 天然提供。

## 每个场景都自带框架边界测试

```bash
cd library   && uv run pytest tests/test_framework_boundaries.py   # 21 条：Canary ↔ FastAPI 接缝
cd telemetry && uv run pytest tests/test_framework_boundaries.py   # 25 条：声明、阶段、失败与回收
```

这些测试**钉住框架当前的行为**，既是回归保护，也是一份可执行的说明：
每条都注明它对应框架的哪个决定、以及逼出了本项目的哪个设计。

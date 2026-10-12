# canary-framework 多场景示例

用**形态刻意不同**的几个真实项目分别压测
[Canary Framework](https://pypi.org/project/canary-framework/) **1.1**，
收集单一场景看不到的框架能力与取舍。

```
library/     场景一：智能图书馆管理系统 + RAG —— 请求驱动的 HTTP API（两层 HTTP 各一版）
telemetry/   场景二：设备遥测采集与告警     —— 时间驱动的常驻守护进程（纯核心，零 web 依赖）
relay/       场景三：门店边缘中继           —— 一个进程两个端口、多个应用 + WebSocket（两层各一版）
pipeline/    场景四：对账单导入流水线       —— HTTP 与队列消费者同进程，两步优雅停机（两层各一版）
shop/        场景五：电商后台的渐进迁移     —— 已有 FastAPI 应用用 mount() 接入路由单元
```

**有 Web 服务的场景都有两版**：`canary_framework.asgi.fastapi` 一版、自研的
`canary_framework.asgi.web` 一版，业务代码只有一份，两版只是各自一层薄的 HTTP。
用 `--stack` 挑一层，两层默认端口不同，可以同时起着用同一个脚本压：

```bash
cd library  && uv run python main.py --stack web      # :8011（fastapi 版在 :8010）
cd relay    && uv run python main.py --stack web      # 对外 :8120，管理 :9120
cd pipeline && uv run python main.py --stack web      # :8130
```

场景五只有 FastAPI 一版——它讲的就是"已有 FastAPI 应用怎么挂路由单元"，`mount()` 挂的
是 `APIRouter`，`asgi.web` 里没有这个概念。

每个目录各自是一个**独立的 uv 工程**（自带 `pyproject.toml` 与 `uv.lock`），
拷出去或作为子模块挂到别的仓库里都能直接跑，互不依赖，也不依赖本仓库根目录。

## 快速开始

```bash
cd library    && uv sync && uv run pytest && uv run python main.py   # http://127.0.0.1:8010/docs
cd telemetry  && uv sync && uv run pytest && uv run python main.py   # 守护进程，Ctrl-C 优雅退出
cd relay      && uv sync && uv run pytest && uv run python main.py   # :8020 对外 + :9020 管理
cd pipeline   && uv sync && uv run pytest && uv run python main.py   # :8030，Ctrl-C 看两步停机
cd shop       && uv sync && uv run pytest && uv run python main.py   # :8040，uvicorn 驱动
```

加 `--stack web` 就是另一层 HTTP（场景一、三、四）。

所有项目默认都是**零外部依赖**的：library 用 SQLite 内存库 + 离线确定性模型，
telemetry 用合成波形 + 内存存储，后三个场景的状态全在内存里。接真实的
PostgreSQL/pgvector、LLM、HTTP 采集源都只需改各自的 `.env`。

测试共 464 条：library 216 + telemetry 58 + relay 102 + pipeline 63 + shop 25。
带两层 HTTP 的那三个场景里，行为测试对两层**各跑一遍**（`conftest.py` 里一个参数化的
`stack` fixture），另有一条 `test_parity.py` 把同一串请求打到两层上逐条比对状态码与
响应体——两层对外的形状必须一致，不一致的地方就是要报告的东西。

## 后三个场景：压扩展包

场景三到五是为[扩展包](https://hotcocoacanary.github.io/Canary-Framework/zh/extensions/asgi/)
（`canary_framework.asgi` / `asgi.fastapi` / `config` / `test`）写的，各自挑了
`library` 那种"一个端口、一个 FastAPI 应用"碰不到的维度：

| | 压的是 | 入口形态 |
|---|---|---|
| [`relay`](relay) | 两个端口、四个应用（FastAPI + 手写 ASGI + WebSocket）、手动 `dispatch`、同一个 `App` 被两个 `Server` 依赖、同一个 `Router` 挂两处、两份 `Settings` | `async with Relay()`，`Server` 不是根单元 |
| [`pipeline`](pipeline) | 自定义阶段对（`serving` / `quiesce`）、两步优雅停机、在途任务的预算与放弃、启动/停止失败的回收、重启、同一种单元的多个实例 | `async with Pipeline()` |
| [`shop`](shop) | `mount()` 到已有 FastAPI 应用（lifespan 驱动）、老 `Depends` 路由与路由单元共存、迁移期的桥、三份配置（含带依赖与钩子的那种） | `uvicorn shop.asgi:app` |

两层 HTTP 的对照也在这三个场景里：同一份业务换一层 HTTP 要改什么、两层的报文差在哪、
各自独有的能力是什么，分别记在每个场景的 `tests/test_stack_fastapi.py` 与
`tests/test_stack_web.py`。

三个场景各自的 README 末尾都有一节"试出来的毛病"，记着这一轮压测发现的框架问题与文档
缺口，每条都有一个最小复现（写成 `tests/test_framework_boundaries.py` 里标着【毛病】的
测试）。

## 1.1 对示例的影响

1.1 把引擎重建在显式依赖图上，两个示例依赖 `canary-framework>=1.1,<2`。对示例代码的改动
只有两处，都来自引擎 API 的改名：

- **`advance()` 改名为 `enter()`。** 场景二用它在整张图启动之后进入自定义的 `@launch` 阶段
  （[daemon.py](telemetry/telemetry/daemon.py)）。
- **`scope.entered[phase]` 改为 `scope.entered(phase)`**，以阶段对象为参数。

1.1 的其他变化——`stop()` 成为单元的动作、失败的 `start()` 自行回收、环在任何钩子运行之前
报告——不需要改示例代码，两边的测试原样通过。

## 1.0 对示例的影响

1.0 沿用 0.10 的核心，并开始遵循语义化版本，两个示例因此只依赖 `canary-framework>=1.0,<2`。
对示例代码的改动只有两处：

- **替换有了正式入口。** 两边测试里各自手写的 `seed()`（直接往 `Scope.instances` 里塞替身）
  换成了框架自带的 `scope_of(root).provide(Cls, fake)`。行为一样——真单元不构造、替身走
  完整生命周期——但替身自己声明的依赖也会推进，且类型不对时当场报错。
- **台账以类型为键。** `scope.entered[phase]` 从列表变成 `dict[type, object]`，遍历单元
  用 `.values()`。

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

## 为什么要多个场景

**缺陷的发现**需要多场景：场景一压的是请求路径上的东西（请求体失败路径、响应校验、
冷启动并发），却从头到尾触发不了一次生命周期失败——uvicorn 在 lifespan 启动失败时
直接杀进程，把问题掩盖了。换成守护进程形态，停止语义上的问题立刻现形。

**取舍的代价**也要两边一起看才清楚。两个例子：

*框架没有接口绑定。* 图上的实例一律由框架无参构造，所以"用哪个实现"这件事回到单元
内部：[场景一](library/app/infra/ai.py)（本地还是远端模型）与
[场景二](telemetry/telemetry/source/sample_source.py)（合成波形还是 HTTP 采集）
长出了同一形状的配置分支。一边看像是接线风格，两边一起看才是框架的取舍。

*但测试的替换缝变好了。* 在生命周期开始前 `scope_of(root).provide(Cls, fake)`，整张图
就拿到替身，**真单元连构造都不会发生**。0.9.x 的 `setattr` 缝做不到这点：被替掉的那棵
子树照样实例化、照样启动。两个场景的测试辅助都用它（[库](library/app/testing.py)、
[遥测](telemetry/telemetry/testing.py)）。

*第四个阶段值不值。* 守护进程需要一个"全图都起来之后"的位置——调度器要等所有单元注册完
作业才能开循环。`@start` 给不了：推进沿依赖向下，调度器作为被依赖方反而最先跑。0.9.x 里
只能靠"根排在拓扑序最后"这条未文档化的性质去绕；现在
[三行声明一个 `@launch` 阶段](telemetry/telemetry/phases.py)就解决了，`after=start`
还顺带保证阶段不会被静默跳过。场景一完全用不到这个能力——它的"全图起来之后"由 ASGI
lifespan 天然提供。

## 每个场景都自带框架边界测试

```bash
cd library   && uv run pytest tests/test_framework_boundaries.py   # 32 条：监听、失败回收、替换（两层各一遍）
cd telemetry && uv run pytest tests/test_framework_boundaries.py   # 25 条：声明、阶段、失败与回收
cd relay     && uv run pytest tests/test_framework_boundaries.py   # 27 条：Server、dispatch、配置单元
cd pipeline  && uv run pytest tests/test_framework_boundaries.py   # 15 条：自定义阶段、失败与回收
cd shop      && uv run pytest tests/test_framework_boundaries.py   # 8 条：mount() 的行为与坑
```

这些测试**钉住框架当前的行为**，既是回归保护，也是一份可执行的说明：
每条都注明它对应框架的哪个决定、以及逼出了本项目的哪个设计。

## 参与 / Community

- 示例的问题与改进：[Issues](https://github.com/HotcocoaCanary/Canary-Framework-Example/issues) 与 PR，见 [CONTRIBUTING](CONTRIBUTING.md)
- 框架的使用问题与提议：[主仓库 Discussions](https://github.com/HotcocoaCanary/Canary-Framework/discussions)
- 框架文档：[hotcocoacanary.github.io/Canary-Framework](https://hotcocoacanary.github.io/Canary-Framework/)
- 安全问题：见 [SECURITY](SECURITY.md)；行为准则：[CODE_OF_CONDUCT](CODE_OF_CONDUCT.md)

## 许可证 / License

Apache-2.0，见 [LICENSE](LICENSE)。

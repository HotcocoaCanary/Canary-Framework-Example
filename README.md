# canary-framework 多场景验证平台

用**形态刻意不同**的真实项目分别压测 [Canary Framework](https://pypi.org/project/canary-framework/)，
收集单一场景看不到的框架能力与缺陷。

当前验证版本：**0.9.3 最终版 @ `fb712de`**（`release/0.9.3`，依赖指向本地工作副本）。
结论见 [`doc/verification-final.md`](doc/verification-final.md)——上一轮提的 12 份报告
9 份实修、2 份随功能删除而消失、1 份转为有意的行为，复验没有发现新的严重问题。
过程记录见 [`doc/verification-0.9.3-beta.md`](doc/verification-0.9.3-beta.md)。

```
apps/
  library/     场景一：智能图书馆管理系统 + RAG —— 请求驱动的 HTTP API（core + web 扩展）
  telemetry/   场景二：设备遥测采集与告警   —— 时间驱动的常驻守护进程（纯 core，不装 [web]）
doc/
  verification-final.md       最终版复验报告 ← 先看这个
  verification-0.9.3-beta.md  内测轮的验证报告（12 份报告是在那一轮提的）
  scenario-matrix.md          跨场景能力矩阵
  bug/                        #009–#033，每份开头标着最终版复验的状态
```

## 快速开始

```bash
uv sync --all-packages
uv run pytest                      # 149 个测试：library 105 + telemetry 44
```

单独跑某个场景：

```bash
cd apps/library    && uv run python main.py   # http://127.0.0.1:8010/docs
cd apps/telemetry  && uv run python main.py   # 守护进程，Ctrl-C 优雅退出
```

两个项目默认都是**零外部依赖**的：library 用 SQLite 内存库 + 离线确定性模型，
telemetry 用合成波形 + 内存存储。接真实的 PostgreSQL/pgvector、LLM、HTTP 采集源
都只需改各自的 `.env`。

## 为什么要多场景

**缺陷的发现**需要多场景：场景一压出了 web 扩展的全部问题（请求体的失败路径、
响应校验、冷启动并发），却从头到尾没触发过一次生命周期失败——uvicorn 在 lifespan
启动失败时直接杀进程，把问题掩盖了。换成守护进程形态，停止语义上的问题立刻现形。

**修复的代价**也需要多场景才看得清：最终版删掉 `provide=` 之后，
[场景一](examples/library/app/infra/ai.py)（选本地还是远端模型）与
[场景二](examples/telemetry/telemetry/source/sample_source.py)（选合成波形还是 HTTP 采集）
**同时**长回了同一形状的配置分支，而场景二的整套时间驱动测试则被迫自己搭替换缝
（`telemetry/testing.py::swap_clock`）。一边看像是项目的接线风格，两边一起看才是框架的取舍。
详见 [`doc/scenario-matrix.md`](doc/scenario-matrix.md)。

## 每个场景都自带框架边界测试

```bash
uv run pytest apps/library/tests/test_framework_boundaries.py    # web 侧边界
uv run pytest apps/telemetry/tests/test_framework_boundaries.py  # 生命周期侧边界
```

这些测试**钉住框架当前的行为**，两个方向都钉：修好的从正面钉（退回去就红），
删掉的从"它不在了"钉（悄悄加回来也红）。web 侧 29 条 + 生命周期侧 18 条。

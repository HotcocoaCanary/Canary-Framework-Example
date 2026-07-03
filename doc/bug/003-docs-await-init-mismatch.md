# 003：文档普遍使用 `await app.init()`，实际 `init()` 是同步方法

- **类型**：文档 bug（系统性）
- **影响版本**：canary-framework 0.5.2 文档（doc/zh 全量核对）
- **发现方式**：Canary-Agent 适配验证的文档审计（`inspect.iscoroutinefunction` 实测）

## 证据

实测（0.5.2 安装包）：

```python
import inspect
from canary_framework.core.module import ModuleBase
from canary_framework.core.service import ServiceBase

inspect.iscoroutinefunction(ModuleBase.init)      # False —— 同步
inspect.iscoroutinefunction(ServiceBase.init)     # False —— 同步
inspect.iscoroutinefunction(ServiceBase.startup)  # True
inspect.iscoroutinefunction(ServiceBase.shutdown) # True
```

`await` 一个非 awaitable 的返回值（`init()` 返回 `None`）会直接 `TypeError: object NoneType can't be used in 'await' expression`——文档示例原样运行必然报错。

受影响文档（8/11 篇，正则 `await \w+\.init\(\)` 全量扫描）：

| 文档 | 出现形式 |
|---|---|
| index.md | `await app.init()` |
| quickstart.md | `await app.init()` |
| lifecycle.md | `await app.init()`（多处，含「模块生命周期」「ASGI 生命周期」「配置」节） |
| configuration.md | `await app.init()` |
| modules.md | `await app.init()` |
| services.md | `await svc.init()` |
| api-reference.md | `await app.init()` |
| dependency-injection.md | `await app.init()` |

注意：`await app.startup()` / `await app.shutdown()` 的写法是**正确**的（确为 async），只有 `init()` 错。

## 期望 vs 实际

- **期望**：文档示例可原样运行。
- **实际**：8 篇文档的 `await ... .init()` 示例运行即 TypeError。本项目 `main.py` 实际用法为同步 `app.init()`，与安装包一致、与文档矛盾。

## 关联的框架行为陷阱（已实测确认）

lifecycle.md「初始化」一节的服务级示例是：

```python
async def init(self):
    await super().init()
```

实测：`core/module/_base.py:189` 对子服务的调用是同步的 `child.init()`，没有
`inspect.isawaitable` 分支。按文档写 `async def init` 的后果是——**init 方法体从不执行**，
只产生一条容易被淹没的 `RuntimeWarning: coroutine 'X.init' was never awaited`：

```python
@service()
class AsyncInit(ServiceBase):
    async def init(self):
        await self.db.connect()   # 永远不会运行！

# app.init() 不报错、不执行、只有 RuntimeWarning —— 静默失败
```

也就是说，照抄 lifecycle.md / configuration.md / web.md 的 `async def init` 示例建立数据库连接，
连接永远建不起来，而首个报错会出现在后续某次使用连接的地方，极难排查。

## 修复建议（按优先级）

1. **文档侧（必须）**：全部 `await app.init()` / `async def init` 示例改为同步写法（本项目
   `main.py` 与各 repository 的实际写法即同步 `init()`，可作参照）。
2. **框架侧（强烈建议，独立于 1）**：`child.init()` 调用处检测返回值
   `inspect.isawaitable`，若是则显式抛 `TypeError`（"init() 必须是同步方法"）或改为支持 await——
   静默不执行是三种结果里最糟的。

## 修复建议

统一为同步调用 `app.init()`，或（更大的设计决定）把 `init()` 变为 async——但那属于 0.5.x 版本策略下的行为变更，需要权衡。文档与实现二者必须收敛到一个。

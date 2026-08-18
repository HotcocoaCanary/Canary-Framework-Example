# Canary Framework 0.9.0 迁移体验与改进建议

> 记录者：Canary-Agent 项目的迁移执行者
> 背景：将项目从 Canary Framework 0.5.x 迁移到 0.9.0
> 目的：供框架团队架构师参考，重点描述真实踩坑、根因判断和优先级建议

## 1. 总体结论

0.9.0 的核心理念是好的：`@cocoa` 标记最小单元、依赖图做拓扑注入、
`@web_cocoa` 自动暴露 ASGI 应用并生成 OpenAPI，整体小而清晰，读源码就能理解。

但目前它更接近一个「设计良好的 DI / Web 内核」，而不是一个能直接承载中型业务系统的框架。
对小型服务、内部工具和教学场景可用性不错；对需要数据库、配置、日志、鉴权、中间件和多人协作的生产项目，
用户还需要自己拼装大量外围能力，并且框架自身在路由自省、版本兼容和诊断能力上还有明显短板。

## 2. 值得保留的优点

- 核心抽象简单，`Canary` 的 `init -> start -> stop` 生命周期和拓扑注入非常容易理解。
- `Canary` 本身是 ASGI 应用，`uvicorn app:app` 和测试驱动都走得通。
- `@web_cocoa` 能自动收集路由并生成 `/openapi.json`、`/docs`、`/redoc`，开发者负担低。
- 依赖注入按 snake_case 属性进行，规则明确，没有隐式容器和复杂注解系统。
- 标记装饰器只 `setattr`、不改造类，单元仍可作为普通类继承和混入，这个方向值得坚持。

## 3. 实际踩到的问题与根因

### 3.1 Router 路由收集会静默丢路由

这是本次迁移中影响最大、最隐蔽的问题。

当前 `web/decorator/introspect.py` 的 `routes_of` 大致逻辑是：

1. 沿 MRO 反序扫描类；
2. 用 `getattr(instance, name)` 取方法；
3. 用「方法名字符串」做 `seen` 去重。

这带来两个实际后果：

**同名方法覆盖/丢路由**

项目里 KB、File、Coll 三个 router mixin 都定义了 `create` 方法。
由于去重只按方法名，后扫描的 `create` 被跳过；更糟的是 `getattr(instance, name)`
会把某个 mixin 的 `create` 解析到 MRO 里第一个同名方法上，导致路由挂错。

最终表现是 `/coll/create` 和 `POST /file/{kb_id}` 静默消失，只保留 `/kb/create`。
我当时只能把 `CollRouter.create`、`FileRouter.create` 分别改名为 `create_coll`、`create_file` 来绕过。

这说明路由收集依赖「用户不重名」这个隐式约定，而继承/mixin 组合恰好是框架鼓励的用法。

**`getattr(instance, name)` 触发 Pydantic 实例属性副作用**

当单元继承或关联 Pydantic 模型时，扫描会触到 `model_fields`、`__fields__`、
`model_computed_fields` 等实例属性，产生 Pydantic 弃用告警。这里应该直接读
`klass.__dict__[name]`，而不是通过实例做属性解析。

### 3.2 配置能力缺失，只能用户自己拼

0.9.0 核心不再提供 `CanaryConfig` / `config`。迁移时我手动写了一个：

```python
@cocoa
class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")
```

然后通过 `deps=[AppConfig]` 注入。方向其实是对的，但框架没有提供任何便利层，
导致 env 加载、默认值、覆盖、测试隔离、密钥脱敏都要各项目重复实现。

对框架而言，这不是「必须内置一个重配置系统」，而是缺一个「标准姿势」和可选扩展。

### 3.3 版本迁移成本高，缺少兼容缓冲

从 0.5.x 到 0.9.0，`@module/@service/@router`、`ModuleBase/ServiceBase/RouterBase`、
`CanaryConfig` 等公共 API 被整体替换。下游基本等于重写装配层，顶层 import 直接失败。

如果未来继续以破坏性方式演进，建议至少提供：

- 每个破坏性变化的迁移说明；
- 短期的 deprecation 别名；
- 一个清晰的版本兼容矩阵。

### 3.4 测试工具链对环境较敏感

当前环境是 Starlette 1.3.1，其 `TestClient` 期望 `httpx2`，而环境里只有旧 `httpx`，
导致 `TestClient` 请求直接挂起。这个问题不是业务代码引起的，但会让新用户在
「照着 README 写第一个测试」阶段就卡住。

框架可以在开发文档里明确测试依赖矩阵，或提供官方测试辅助入口。

## 4. 优先级建议

### P0：先修 Router

Router 是正确性和开发者信任的最大瓶颈，建议优先处理：

1. `routes_of` 和 `hooks_of` 改为读取 `klass.__dict__[name]`，不要用 `getattr(instance, name)`。
2. 去重不能只按方法名字符串，应按方法身份或所在类，避免 mixin 同名方法互相覆盖。
3. 对重复路径/重复方法给出启动期错误，错误信息要包含类名、方法名、完整路径。
4. 增加装配期校验：handler 的每个参数都必须能被解析为 body/path/query/header/cookie，
   否则直接报错并指出是哪个 handler、哪个参数，而不是静默丢默认值。
5. 提供一等公民的请求/响应模型，以及可选的 prefix、tags、分组能力，减少用户手写全路径。

### P1：补一层 Config 扩展

建议基于 `pydantic-settings` 做一个轻量 `@config` 装饰器，但保持「配置仍是普通 cocoa 单元、
通过 `deps` 注入」的模型：

- 支持 env、文件、默认值和优先级合并；
- 支持测试时的配置覆盖/作用域隔离，避免全局单例；
- 提供密钥字段的日志脱敏钩子；
- 文档给出唯一推荐用法，不要让每个项目发明自己的写法。

### P2：补 Logging 扩展

日志建议作为扩展、不要进 core：

- 结构化日志；
- `request_id` 等上下文贯穿；
- 生命周期和路由访问日志；
- 敏感字段脱敏；
- 与 config 的日志级别联动。

## 5. 本次迁移为绕过问题做的临时处理

这些处理对架构师评估框架现状有参考价值：

- 三个 router 的同名 `create` 方法改名为 `create_coll`、`create_file`，以避开路由收集丢路由。
- 路由路径从 `prefix + path` 改成在每个装饰器里写完整路径，因为当前收集模型对组合不够可靠。
- 测试客户端改用 `httpx.ASGITransport`，避开 `starlette.testclient.TestClient` 对 `httpx2` 的依赖。

这些都不是框架本应强迫用户做出的选择，说明 router 的「组合语义」和测试/环境兼容性
是当前最值得投入的两块。

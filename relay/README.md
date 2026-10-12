# 场景三：门店边缘中继

一个进程，**两个端口，四个应用**。连锁门店的边缘机上跑着它：店里的 POS、电子秤、传感器
把心跳和事件推给它，它对门店内网提供接入 API 与一条 WebSocket 实时流，对运维网段另开一个
只绑回环的管理端口。

它存在的目的是压 `canary_framework.web.asgi` 的那几条规则——**应用是值，端口才需要唯一**——
以及 `library` 单个端口、单个应用时碰不到的那些边角。

**同一份业务，两层 HTTP。** HTTP 这一层是可换的，其余全部共用：

| 这一层 | 它是什么 | 它带来什么 |
|---|---|---|
| [`relay/http/fastapi.py`](relay/http/fastapi.py) | 两个**原生 FastAPI 应用**（模块级 `APIRouter` + `Depends` + [`bridge.py`](relay/http/bridge.py) 那座桥），由我们的 `Server` 服务 | OpenAPI、`/docs`、`tags` |
| [`relay/http/canary.py`](relay/http/canary.py) | 路由与应用都是单元（`canary_framework.web.asgi.app`） | 只依赖 pydantic，没有 OpenAPI |

框架不再包装 FastAPI——没有适配层，也不需要：ASGI 两边各守协议即可任意组合。本场景把三种
组合都摆了出来：**我们的应用单元配我们的 `Server`**（canary 层）、**原生 FastAPI 配我们的
`Server`**（fastapi 层），而**手写的可调用单元配谁都行**（下面那两个）。

共用的不止业务：`/metrics` 与 `/ws/events` 是**普通的 `Canary` 单元加一个
`async def __call__(scope, receive, send)`**，跟任何 Web 框架都无关，两层直接用同一份
（[`metrics.py`](relay/metrics.py) / [`events.py`](relay/events.py)）；管理口的口令校验也是
一个普通 ASGI 中间件（[`plain.py`](relay/plain.py) 的 `guard`），两层共用，所以两边的 403
必然一致。

```bash
uv sync
uv run pytest                                   # 100 个测试（行为测试跑两遍）

uv run python main.py                           # canary 版（默认）：对外 :8020，管理 :9020
uv run python main.py --stack fastapi           # 原生 FastAPI 版：对外 :8120，管理 :9120
uv run python main.py --stack fastapi --public-port 8888 --admin-port 9888
```

两层默认端口差 100（fastapi 版 +100），所以可以同时起着、用同一个脚本压。两个 `Server`
都带 `access_log=False`（`web.asgi.server.Server` 的类参数原样传给 `uvicorn.Config`）。

依赖只有三条：`canary-framework[config,web]`（`[web]` = `[app]` 的 pydantic + `[server]`
的 uvicorn）、`fastapi`（第二层自己要的）、`websockets`（uvicorn 的 WebSocket 实现）。
默认零外部依赖：状态全在内存里，时钟可替换，没有数据库也没有外部服务。

## 结构

```
Relay                        根单元，自己不监听任何东西
├─ PublicServer   :8020      canary 层是"依赖即服务"，fastapi 层手动 dispatch
│  ├─ PublicApi      /          HTTP API：/devices、/health（应用单元 或 FastAPI 对象）
│  ├─ EventStream    /ws/events  普通单元 + __call__（两层共用）
│  └─ Metrics        /metrics    普通单元 + __call__（两层共用）     ←┐
├─ AdminServer    :9020      两层都手动拼表 —— @init 里给 self.app 赋值 │ 同一个实例
│  ├─ AdminApp       /admin     第二个 HTTP 应用：/admin/fleet         │
│  ├─ Metrics        /metrics   ───────────────────────────────────────┘
│  └─ ready()        /          一个连单元都不是的 ASGI 函数
└─ Reaper                    后台巡检循环，把心跳超时的设备标记离线

共享的叶子：Fleet（台账）· Counters（计数）· Clock（时钟）· EdgeSettings / AdminSettings（两份配置）
```

装配的骨架在 [`relay/server.py`](relay/server.py)，它与用哪一层 HTTP 无关：三个单元各留一个
类型注解（`api` / `console` / `public` / `admin`），由两层各给出那一条 `dep()`（fastapi 层
的对外应用不是单元，所以那一条在 `@init` 里拼）。基类**不写** `dep()` 的默认值——两层是并列
的，而且 `relay.server` 写死任一层就会和 `relay.http.*` 形成循环导入。

## 这个场景压的是什么

| 维度 | 在哪 |
|---|---|
| 一个进程两个端口，`Server` 不是根单元 | [`server.py`](relay/server.py) |
| 同一个应用单元被两个 `Server` 依赖（一个实例，两个端口） | `Metrics`，[测试](tests/test_admin.py) |
| 一个端口多个应用，按 `path` 分发 | canary 层 `PublicServer` 的三条 `dep()` |
| 不属于任何 Web 框架的可调用单元（手写 ASGI） | [`metrics.py`](relay/metrics.py)、[`plain.py`](relay/plain.py) |
| WebSocket（原生 ASGI，带订阅过滤与背压） | [`events.py`](relay/events.py) |
| 手动 `dispatch`，表里混进一个非单元的 ASGI 函数 | `AdminServer.assemble()` |
| 一个端口上既有 FastAPI 应用又有两个手写可调用单元 | fastapi 层 `PublicServer` 的 `@init` |
| 原生 FastAPI 的接口怎么拿到图上的单元 | [`http/bridge.py`](relay/http/bridge.py) |
| 同一个路由单元被两处依赖（`/health` 与 `/admin/health`） | `HealthApi`，[`http/canary.py`](relay/http/canary.py) |
| 两份配置（两个 `Settings` 单元，各读自己的 `env_prefix`） | [`settings.py`](relay/settings.py) |
| 配置自己有依赖与钩子 | `AdminSettings` → `SecretStore` |
| 后台循环与 HTTP 并存 | [`reaper.py`](relay/reaper.py) |
| 两层 HTTP 可换，其余全部共用 | [`relay/http/`](relay/http) |
| 测试：`port = 0` 真实套接字 / `ASGITransport` / 自己当服务器喂 ASGI 消息 | [`tests/`](tests) |
| 两层逐条比对（含 `/metrics` 的文本与管理口的 403） | [`tests/test_parity.py`](tests/test_parity.py) |

## 四件做之前没想到的事

**`Server` 的 `host` / `port` 从配置来，要写在 `@init`。** 它们是普通类属性，所以赋值就行；
`@init` 早于 `@start`（也就是早于绑定端口），时序是对的。`@start` 里赋值就晚了。

**赋了 `self.app`，依赖的应用单元就不再自动加入。** 这是文档写了的，但真用起来才感觉到
它的代价：`AdminServer` 依赖 `Metrics`、`Metrics` 也确实启动了，只是忘了写进 `dispatch`
的表里就不会被服务——**不报错，不警告**。"依赖即服务"（服务器直接依赖的可调用单元，各自
应答自己的 `path`，没有 `path` 属性的应答 `/`）的好处正是它消掉了这个漏写的可能，手动拼装
把这个可能还回来了。fastapi 层的对外端口只能手动拼——一个端口上既有 FastAPI 应用又有两个
手写的可调用单元；canary 层那边三条 `dep()` 就完事。

**`path` 不是 `/` 的 FastAPI 应用，要自己把 `docs_url` 挪进前缀。** `dispatch` 只转发、
不改写路径（这是对的，有些协议的端点就在根上），所以第二个 FastAPI 应用的默认
`/docs`、`/openapi.json` 根本不会被分发到它。`create_admin()` 因此显式写了
`docs_url="/admin/docs"`、`openapi_url="/admin/openapi.json"`。忘了写的症状很迷惑：接口
全是好的，只有文档 404。

**异常处理器与中间件是每个应用各自的。** 这个进程里每个端口上都有一个 HTTP 应用，而它们
**共享**同一个东西：canary 层是同一个 `HealthApi` **单元**被两处依赖（一个实例，`/health`
与 `/admin/health` 两套 URL），fastapi 层是同一个 `site_health` **函数**被两个 `APIRouter`
挂两次。共享的那部分抛出来的领域异常（[`errors.py`](relay/errors.py) 的 `UnknownDevice`），
要在两个应用上各落地一次：fastapi 层是两个 `create_*()` 各 `add_exception_handler` 一行，
canary 层是两个 `App` 单元各写一个 `@error(UnknownDevice)`。口令中间件同理——`guard` 是
共用的那一份，但"包在哪个应用上"两层各写一次。路由能共享，应用级的配置不能。

## 试出来的毛病

上一轮试出三条，**现在都修好了**——下面保留原来的说法，并写明修成了什么样；对应的测试
从"钉住毛病"改成了正向断言，在
[`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py)（28 条）里。

1. ~~**在途请求没有上限。**~~ **已修**：`Server` 的类参数现在原样传给
   `uvicorn.Config`，所以 `class Gateway(Server, timeout_graceful_shutdown=10,
   proxy_headers=True, access_log=False)` 就是入口。
   [`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py) 里那条
   【毛病】因此改成了两条正向断言：不配超时就等在途请求做完，配了 1s 就只等 1s。
2. ~~**`port = 0` 只在第一次成立。**~~ **已修**：服务期间 `server.port` 是实际端口，停止
   后还原成声明的值，所以重启会重新分配。测试改成了正向断言——同一个服务器对象重启之后
   换了端口，老端口被别人占着也照样起得来。
3. ~~**`dispatch` 对 `lifespan` 的 scope 沉默。**~~ **已修**：现在它自己应答
   `startup.complete` / `shutdown.complete`，并且**不**把消息转发给子应用（应用单元的启动
   与回收归 Canary 管）。应用单元的 `App` 也一样处理。

### 换到应用单元那一层时要知道的差异

这几条不算毛病（都是 `web.asgi.app` 的选择，文档里写明了），但换层时会碰到：

4. **校验失败的报文差两处。** `loc` 与 `type` 一致，但 ①`input` 字段只有 FastAPI 有；
   ②`msg` 的措辞不同——应用单元那一层校验的是**原始 JSON 字节**（JSON 模式，`strict=True`
   的模型因此也能用），FastAPI 校验的是**解析后的 Python 对象**。于是同一个 `dict_type`
   错误一边说 "Input should be a valid dictionary"，另一边说 "Input should be an object"。
   普通模型的接受/拒绝是一致的。最小复现在
   [`tests/test_parity.py`](tests/test_parity.py) 的最后一条。
5. **没有列出路由表的办法。** FastAPI 那层读 `/openapi.json` 就有；应用单元那一层既没有
   OpenAPI 也没导出路由表，本仓的 `paths_of`（见 `library/app/testing.py`）只能去动非公开
   的 `canary_framework.web.asgi.app.router.collect`。框架那边记着，之后单独讨论。
6. **尾斜杠的行为与 FastAPI 相反。** 应用单元那一层严格区分、不重定向（`/devices/` →
   404），FastAPI 会 307 跳到正确的那个。两层各有一条测试钉着
   （`test_stack_canary.py` / `test_stack_fastapi.py`）。
7. ~~**同步接口方法会卡住整个进程。**~~ **已修**：普通 `def` 的接口与 `@error` 处理器现在
   走 `asyncio.to_thread`。代价是线程池里的方法与事件循环并发，读写单元状态要自己保证
   线程安全。正向断言在
   [`library/tests/test_parity.py`](../library/tests/test_parity.py) 的最后两条。

另外两条不算毛病，但文档值得补一句：

- **`canary-framework[server]` 只装 uvicorn，不带 WebSocket 实现。** `path = "/ws/..."` 的
  应用单元写好了也握不上手，要自己加 `websockets` 或 `wsproto`。本项目的
  `pyproject.toml` 里因此多一条依赖。
- **WebSocket 被 `dispatch` 拒绝时，客户端看到的是 HTTP 403，不是 close code 1008。**
  按 ASGI 的规定，accept 之前关闭就是握手失败；`dispatch` 写的那个 1008 客户端拿不到。

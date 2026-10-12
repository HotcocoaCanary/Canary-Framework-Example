# 场景三：门店边缘中继

一个进程，**两个端口，四个应用**。连锁门店的边缘机上跑着它：店里的 POS、电子秤、传感器
把心跳和事件推给它，它对门店内网提供接入 API 与一条 WebSocket 实时流，对运维网段另开一个
只绑回环的管理端口。

它存在的目的是压 `canary_framework.asgi` 的那几条规则——**应用是值，端口才需要唯一**——
以及 `library` 单个端口、单个 FastAPI 应用时碰不到的那些边角。

**同一份业务，两层 HTTP。** HTTP 这一层是可换的，其余全部共用：

| 这一层 | 包 | 它带来什么 |
|---|---|---|
| [`relay/http/fastapi.py`](relay/http/fastapi.py) | `canary_framework.asgi.fastapi` | OpenAPI、`/docs`、`tags` |
| [`relay/http/web.py`](relay/http/web.py) | `canary_framework.asgi.web` | 只依赖 pydantic，没有 OpenAPI |

共用的不止业务：`/metrics` 与 `/ws/events` 是**手写的 ASGI 应用单元**，跟 Web 框架无关，
两层直接用同一份；管理口的口令校验也是一个普通 ASGI 中间件（[`plain.py`](relay/plain.py)
的 `guard`），两层共用，所以两边的 403 必然一致。

```bash
uv sync
uv run pytest                               # 99 个测试（行为测试跑两遍）

uv run python main.py                       # fastapi 版：对外 :8020，管理 :9020
uv run python main.py --stack web           # web 版：对外 :8120，管理 :9120
uv run python main.py --stack web --public-port 8888 --admin-port 9888
```

两层默认端口差 100，所以可以同时起着、用同一个脚本压。四个 `Server` 都带
`access_log=False`（`asgi.Server` 的类参数原样传给 `uvicorn.Config`）。

默认零外部依赖：状态全在内存里，时钟可替换，没有数据库也没有外部服务。

## 结构

```
Relay                        根单元，自己不监听任何东西
├─ PublicServer   :8020      依赖即服务 —— 三个应用单元各自应答自己的 path
│  ├─ PublicApi      /          HTTP API：/devices、/health（fastapi 版或 web 版）
│  ├─ EventStream    /ws/events  手写的 WebSocket 应用
│  └─ Metrics        /metrics    手写的 Prometheus 应用   ←┐
├─ AdminServer    :9020      手动拼装 —— @init 里给 self.app 赋值   │ 同一个实例
│  ├─ AdminApp       /admin     第二个 HTTP 应用：/admin/fleet       │
│  ├─ Metrics        /metrics   ───────────────────────────────────┘
│  └─ ready()        /          一个连单元都不是的 ASGI 函数
└─ Reaper                    后台巡检循环，把心跳超时的设备标记离线

共享的叶子：Fleet（台账）· Counters（计数）· Clock（时钟）· EdgeSettings / AdminSettings（两份配置）
```

装配的骨架在 [`relay/server.py`](relay/server.py)：三个单元只留一个类型注解
（`api` / `console` / `public` / `admin`），由两层各给出那一条 `dep()`。基类**不写**
`dep()` 的默认值——依赖按类型收集，不像钩子那样按属性名覆盖，基类写了那条边就也成立
（`pipeline` 场景里有最小复现）。

## 这个场景压的是什么

| 维度 | 在哪 |
|---|---|
| 一个进程两个端口，`Server` 不是根单元 | [`server.py`](relay/server.py) |
| 同一个应用单元被两个 `Server` 依赖（一个实例，两个端口） | `Metrics`，[测试](tests/test_admin.py) |
| 一个端口多个应用，按 `path` 分发 | `PublicServer` 的三个 `dep()` |
| 不是 FastAPI 的应用单元（手写 ASGI） | [`metrics.py`](relay/metrics.py)、[`plain.py`](relay/plain.py) |
| WebSocket（原生 ASGI，带订阅过滤与背压） | [`events.py`](relay/events.py) |
| 手动 `dispatch`，表里混进一个非单元的 ASGI 函数 | `AdminServer.@init` |
| 同一个路由单元被两处依赖（`/health` 与 `/admin/health`） | [`api/health.py`](relay/api/health.py) |
| 两份配置（两个 `Settings` 单元，各读自己的 `env_prefix`） | [`settings.py`](relay/settings.py) |
| 配置自己有依赖与钩子 | `AdminSettings` → `SecretStore` |
| 后台循环与 HTTP 并存 | [`reaper.py`](relay/reaper.py) |
| 两层 HTTP 可换，其余全部共用 | [`relay/http/`](relay/http) |
| 测试：`port = 0` 真实套接字 / `ASGITransport` / 自己当服务器喂 ASGI 消息 | [`tests/`](tests) |
| 两层逐条比对（含 `/metrics` 的文本） | [`tests/test_parity.py`](tests/test_parity.py) |

## 四件做之前没想到的事

**`Server` 的 `host` / `port` 从配置来，要写在 `@init`。** 它们是普通类属性，所以赋值就行；
`@init` 早于 `@start`（也就是早于绑定端口），时序是对的。`@start` 里赋值就晚了。

**赋了 `self.app`，依赖的应用单元就不再自动加入。** 这是文档写了的，但真用起来才感觉到
它的代价：`AdminServer` 依赖 `Metrics`、`Metrics` 也确实启动了，只是忘了写进 `dispatch`
的表里就不会被服务——**不报错，不警告**。"依赖即服务"的好处正是它消掉了这个漏写的可能，
手动拼装把这个可能还回来了。

**`path` 不是 `/` 的 FastAPI 应用，要自己把 `docs_url` 挪进前缀。** `dispatch` 只转发、
不改写路径（这是对的，有些协议的端点就在根上），所以第二个 FastAPI 应用的默认
`/docs`、`/openapi.json` 根本不会被分发到它。`AdminApp` 因此显式写了
`docs_url="/admin/docs"`。忘了写的症状很迷惑：接口全是好的，只有文档 404。

**异常处理器与中间件是每个应用单元各自的。** 这个进程里有两个 FastAPI 应用，还有一个被
两边**共同依赖**的 `HealthApi`——共享路由抛出来的领域异常，要在两个应用上各落地一次。
于是 [`errors.py`](relay/errors.py) 给出一个 `install_errors(app)`，两个 `App` 的 `@init`
各调一次。路由能共享，应用级的配置不能。

## 试出来的毛病

三条写成了测试，在 [`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py)
里标着 **【毛病】**。断言钉的是"现在是什么样"，注释写的是"应该是什么样"。

1. ~~**在途请求没有上限。**~~ **已修**：`asgi.Server` 的类参数现在原样传给
   `uvicorn.Config`，所以 `class Gateway(asgi.Server, timeout_graceful_shutdown=10,
   proxy_headers=True, access_log=False)` 就是入口。
   [`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py) 里那条
   【毛病】因此改成了两条正向断言：不配超时就等在途请求做完，配了 1s 就只等 1s。
2. **`port = 0` 只在第一次成立。** `@start` 把实际端口写回 `self.port`，"请求的端口"和
   "实际端口"共用一个属性。于是重启时拿着上次分到的端口去绑，那个端口可能已经被别人占了。
3. **`dispatch` 对 `lifespan` 的 scope 沉默。** 框架自己的 `Server` 用 `lifespan="off"`，
   碰不到；但 `dispatch` 是公开导出的函数，拼出来的应用交给任何会驱动 lifespan 的东西
   （Starlette `TestClient`、`uvicorn --lifespan on`、`asgi-lifespan`）都会一直等
   `lifespan.startup.complete`。

### 换到 asgi.web 时要知道的差异

这几条不算毛病（都是 `asgi.web` 的选择，文档里写明了），但换层时会碰到：

4. **校验失败的报文差两处。** `loc` 与 `type` 一致，但 ①`input` 字段只有 FastAPI 有；
   ②`msg` 的措辞不同——`asgi.web` 校验的是**原始 JSON 字节**（JSON 模式，`strict=True`
   的模型因此也能用），FastAPI 校验的是**解析后的 Python 对象**。于是同一个 `dict_type`
   错误一边说 "Input should be a valid dictionary"，另一边说 "Input should be an object"。
   普通模型的接受/拒绝是一致的。最小复现在
   [`tests/test_parity.py`](tests/test_parity.py) 的最后一条。
5. **没有列出路由表的办法。** FastAPI 那层读 `/openapi.json` 就有；`asgi.web` 既没有
   OpenAPI 也没导出路由表，本仓的 `paths_of`（见 `library/app/testing.py`）只能去动非公开
   的 `canary_framework.asgi.web.router.collect`。框架那边记着，之后单独讨论。
6. **尾斜杠的行为与 FastAPI 相反。** `asgi.web` 严格区分、不重定向（`/devices/` → 404），
   FastAPI 会 307 跳到正确的那个。两层各有一条测试钉着
   （`test_stack_web.py` / `test_stack_fastapi.py`）。
7. ~~**同步接口方法会卡住整个进程。**~~ **已修**：普通 `def` 的接口与 `@error` 处理器现在
   走 `asyncio.to_thread`，两层一致。代价是线程池里的方法与事件循环并发，读写单元状态要
   自己保证线程安全。正向断言在
   [`library/tests/test_parity.py`](../library/tests/test_parity.py) 的最后两条。

另外两条不算毛病，但文档值得补一句：

- **`canary-framework[asgi]` 只装 uvicorn，不带 WebSocket 实现。** `path = "/ws/..."` 的
  应用单元写好了也握不上手，要自己加 `websockets` 或 `wsproto`。本项目的
  `pyproject.toml` 里因此多一条依赖。
- **WebSocket 被 `dispatch` 拒绝时，客户端看到的是 HTTP 403，不是 close code 1008。**
  按 ASGI 的规定，accept 之前关闭就是握手失败；`dispatch` 写的那个 1008 客户端拿不到。

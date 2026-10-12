# 场景四：对账单导入流水线

HTTP 接入与队列消费者**在同一个进程里**，停机是两步的：先关闸，再把在途的做完，最后才
回收。财务的对账单从几个渠道推进来，接入口收下就入队返回 202，后台的消费者一行一行记进
账本——所以"优雅停机"在这里不是一句话，而是**在途请求**和**在途任务**两种东西要按不同
顺序收尾。

它压的是 `canary_framework` 的阶段机制：框架自带三个阶段，这个场景加了第四、第五个。

**同一份业务，两层 HTTP。** HTTP 在这条流水线上只是接入口，队列、消费者、账本、闸门与
停机的两个阶段都在业务那一侧，两层共用：

| 这一层 | 它是什么 | 它带来什么 |
|---|---|---|
| [`pipeline/http/canary.py`](pipeline/http/canary.py) | 路由与应用都是单元（`canary_framework.web.asgi.app`） | 依赖写在类上，只依赖 pydantic，没有 OpenAPI |
| [`pipeline/http/fastapi.py`](pipeline/http/fastapi.py) | 一个**原生 FastAPI 应用**（模块级 `APIRouter` + `Depends`） | OpenAPI、`/docs`、`tags` |

框架不包装 FastAPI——ASGI 两边各守协议就能任意组合，不该有适配层。所以这个场景摆出的是
**两种组合**，而两边都由我们的 `canary_framework.web.asgi.server.Server` 服务：

* **原生 FastAPI 应用 + 我们的 `Server`**：服务器单元在 `@init` 里
  `self.app = create_app(self.lanes)`；端点是模块级函数，所以要一座按类型取单元的桥
  （[`bridge.py`](pipeline/http/bridge.py)：`app.state.graph` + `use(Cls)`），还要一个
  组合根单元 `Lanes`——这一层没有应用单元替它拢住那张图。
* **我们的应用单元 + 我们的 `Server`**：应用单元自己就是 ASGI 应用，`dep(IngestApp)`
  就是"服务它"；依赖直接写在路由类上，不需要桥也不需要组合根。

```bash
uv sync
uv run pytest                              # 66 个测试（行为测试跑两遍）

uv run python main.py                      # canary 版，:8030
uv run python main.py --stack fastapi      # 原生 FastAPI 版，:8130，带 /docs
uv run python main.py --stack fastapi --port 9999
```

Ctrl-C 看两步停机的日志。两层端口差 100（fastapi 版 +100），可以同时起着压；`IngestServer`
带 `access_log=False`（`Server` 的类参数原样传给 `uvicorn.Config`）。

默认零外部依赖：队列是 `asyncio.Queue`，账本是内存里的 dict。

## 结构

```
Pipeline                     根单元，它推进那两个自定义阶段
├─ IngestServer   :8030      唯一的端口
│  └─ IngestApp      /           应用单元，自己就是 ASGI 应用
│     ├─ BatchApi    /batches    提交即入队，不等做完
│     └─ StatusApi   /status     队列深度、在途、停机日志、给 LB 的 503
├─ FastLane                  小批量通道：2 个消费者 + FastQueue
├─ BulkLane                  大批量通道：1 个消费者 + BulkQueue
└─ Gate · JobBook · Ledger · Journal · PipelineSettings
```

这是 canary 层的形状。fastapi 层只换掉中间那一截：`IngestApp` 变成一个原生 FastAPI 应用
（路由与端点在模块级），`IngestServer` 改为 `dep(Lanes)` 并在 `@init` 里把那个应用赋给
`self.app`。端口之下、`Gate` 之上的东西一个没动。

## 两个自定义阶段

```python
quiesce = Phase("quiesce")
serving = Phase("serving", after=start, leave=quiesce)
```

框架给的两条规则互为镜像，而**两步停机需要两个方向**：

| | 方向 | 适合 |
|---|---|---|
| `enter(root, serving)` | 依赖在前 | 准备资源：队列先有，消费者才起 |
| `leave(root, serving)` | **本单元在前** | 停止接受：根先关闸，再轮到各通道排空 |

所以"关闸"必须写成一次 `leave`。写成 `Phase("quiesce", after=start)` 再 `enter` 它的话，
顺序会反过来——队列（被依赖的一方）先关、消费者后知道、最该先关的接入口最后知道。
这一条在 [`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py) 的第一条
测试里钉着。

于是一次完整的停机长这样（`uv run python main.py` 之后 Ctrl-C 就能看到）：

```
quiesce: 关闸（/status/health 开始回 503）      ← 根单元，第一步
quiesce: fast 通道排空完成，剩 0 个              ← 两条通道，第二步
quiesce: bulk 通道排空完成，剩 0 个
stop: fast 通道收工，完成 7 个                   ← 框架的 @stop，第三步
stop: bulk 通道收工，完成 2 个
```

关键在第一步与第三步之间：**端口还在监听**，`/status/health` 已经回 503。上游的负载均衡
有时间把流量摘走，而在途的请求和在途的任务照常做完。`@stop`（真正关监听、收消费者）在这
之后才跑。

## 这个场景压的是什么

| 维度 | 在哪 |
|---|---|
| 自定义阶段，以及一个阶段的两个方向 | [`phases.py`](pipeline/phases.py)、[`app.py`](pipeline/app.py) |
| 后台消费者与 HTTP 并存 | [`workers.py`](pipeline/workers.py) |
| 在途任务的回收顺序与预算 | `@quiesce` + `drain_timeout_seconds` |
| 排空超时后放弃，并说清楚下场 | 任务终态 `abandoned`，[测试](tests/test_shutdown.py) |
| 同一种东西的多个实例（子类） | [`lanes.py`](pipeline/lanes.py)：两条通道 |
| 启动失败时的回收（自定义阶段不会被推进） | [boundaries](tests/test_framework_boundaries.py) |
| 停止失败时其余单元照常回收（`ExceptionGroup`） | 同上 |
| 重启（`@start` 再跑，`@init` 不再跑） | [`test_shutdown.py`](tests/test_shutdown.py) |
| 两种组合都由我们的 `Server` 服务：原生 FastAPI 应用 / 我们的应用单元 | [`pipeline/http/`](pipeline/http) |
| 原生 FastAPI 的端点去图上取单元（那座三行的桥） | [`pipeline/http/bridge.py`](pipeline/http/bridge.py) |
| 没有应用单元时谁来拢住那张图（组合根） | [`fastapi.py`](pipeline/http/fastapi.py) 的 `Lanes` |
| 测试：`port = 0` / `ASGITransport` / 纯对象三种粒度 | [`tests/`](tests) |
| 两层逐条比对（含 503 + `Retry-After`、429、404） | [`tests/test_parity.py`](tests/test_parity.py) |
| 只有一层才有的东西（OpenAPI、`/docs`） | [`tests/test_stacks.py`](tests/test_stacks.py) |

## 三件做之前没想到的事

**"可回收的资源"必须放在 `@start`，不能放在 `@init`。** `stop()` 只把 `start`（以及以它
为前驱的阶段）还原成空闲，`init` 仍然是"已进入"。所以在 `@init` 里建、在 `@stop` 里拆的
东西，重启之后**不会被重建**——第二次 `start()` 拿到的是一个已经关掉的队列。这个场景因此
把队列建在 `@start`，把账本建在 `__init__`（它不是资源，重启不该丢账），`@init` 只留给
"建一次就不动的东西"，比如 FastAPI 应用本身。

**"接活/不接活"这件状态要有自己的节点。** 接入口（路由单元）和根单元都要碰它：根单元的
`@quiesce` 关它，路由单元读它决定要不要收。路由不能依赖根（那是一个环），所以它是一个
单独的 [`Gate`](pipeline/gate.py)。这不是框架的限制，是依赖图逼出来的明确结论——
放在根上会立刻报环，而不是等到运行时才出问题。

**通道数不能由配置决定。** "同一种东西的多个实例"在这个框架里就是"多个子类"：
`FastLane` / `BulkLane` 各是图上的一个节点，`dep(FastLane)` 自己就是那个名字，不需要工厂
也不需要给实例起名。代价是数量写在代码里：想要"每个租户一条通道"就走不通了——那需要
运行期构造实例，而图是静态的。这是明确的取舍，不是疏漏。

## 试出来的毛病

两条，第一条已经修了。

~~**子类用同名属性覆盖一条 `dep()`，基类那条边仍然成立。**~~ **已修**：依赖现在和钩子
一样按**属性名**解析。上一轮的问题是这样的——

```python
class Pool(Canary):
    queue = dep(JobQueue)       # 基类给个默认

class FastLane(Pool):
    queue = dep(FastQueue)      # 子类换掉它
```

`self.queue` 读到的是 `FastQueue`（属性遮蔽，没问题），但当时 `JobQueue` **也**在图上：
构造、`@start`、`@stop` 全跑一遍，只是没有人用它——一个连接池被这样白开一份就不只是浪费。
那时的绕法是基类只留类型注解。现在基类那条边随覆盖消失，所以
[`workers.py`](pipeline/workers.py) 写回了最自然的样子：基类一条默认 `dep()`，两条通道各
换一个队列。对应的测试在
[`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py)，改成了正向断言
（连"覆盖成非 `dep` 则这条依赖消失"也一并钉住）。

第二条不算毛病，是把同一份业务换到应用单元那一层时要知道的差异：

**校验失败的报文差两处。** `loc` 与 `type` 一致，但 ①`input` 字段只有 FastAPI 有；
②`msg` 的措辞不同——应用单元那一层校验的是原始 JSON 字节（JSON 模式），FastAPI 校验的是
解析后的 Python 对象。普通模型的接受/拒绝一致。最小复现在 `relay` 场景的
[`tests/test_parity.py`](../relay/tests/test_parity.py) 最后一条。

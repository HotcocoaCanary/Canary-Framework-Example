# 场景五：电商后台的渐进迁移

一个**已经在跑**的 FastAPI 电商后台。老接口在 `/v1`：模块级的 `APIRouter`、模块级的状态、
`Depends`。要把它迁到 Canary 上，而且不能停、不能一次改完。

迁移靠的是**协议层的兼容**，不是什么适配层：框架的服务器单元服务任何 ASGI 应用，框架的
应用单元也能被任何 ASGI 服务器服务。于是迁移可以分成两步，每一步都能单独上线。

```bash
uv sync
uv run pytest                      # 32 个测试（老接口的断言两个阶段各跑一遍）

uv run python main.py              # 阶段一：老应用一行不改，只换服务器（:8040/docs）
uv run python main.py --stage 2    # 阶段二：新模块与老应用按路径并存（:8041）
uv run python main.py --stage 2 --port 9000
```

## 两个阶段

全部接缝在 [`shop/server.py`](shop/server.py) 一个文件里。

**阶段一：只换服务器。** 老应用一行不改，由我们的 `Server` 服务它：

```python
class Stage1(Server, access_log=False):
    graph = dep(ShopGraph)          # 业务那一半：商品目录、算钱规则、三份配置

    @init
    def build(self) -> None:
        self.app = create_legacy(self.graph)    # 一个普通的 FastAPI 对象
```

这一步什么都没搬，但已经换到了想要的东西：**进程的生命周期归 Canary**。数据库、缓存、
后台任务都是图上的单元，按依赖顺序启动与回收，不必再往 FastAPI 的 lifespan 里手工拼。
`Server` 只认 ASGI 协议，所以它不在乎 `self.app` 是 FastAPI、Starlette 还是手写的函数。

**阶段二：新模块作为另一个 ASGI 应用并存。** 迁过来的模块是一个应用单元（`V2Api`，
`path = "/v2"`），和老应用一起按路径分发：

```python
class Stage2(Server, access_log=False):
    graph = dep(ShopGraph)
    v2 = dep(V2Api)                 # 新模块：路由是单元，应用也是单元

    @init
    def build(self) -> None:
        self.app = dispatch({self.v2.path: self.v2, "/": create_legacy(self.graph)})
```

两边共用同一张图上的业务单元，所以 `/v2` 改掉的库存，`/v1` 立刻看得见。老那边继续用它的
`Depends`，新那边用 `dep()`，谁也不必迁就谁。

### 为什么不是"把路由挂到老应用上"

那需要框架去包装 FastAPI 的 `APIRouter`——一个只为某个 web 框架存在的适配层。上一轮这个
场景正是那么写的（`mount(root, app)`），这一轮框架把它删掉了，理由是：ASGI 的意义就是
两边各自守协议即可任意组合，中间不该有一层。

按路径分发不需要适配层，代价也看得见：

- **两份 OpenAPI。** `/docs` 只有老应用那一份；新模块那一层不生成 OpenAPI。
- **前缀要自己对齐。** `dispatch` 只转发、**不改写** `path`，所以 `V2Api` 下面的路由单元
  自己带着 `/v2`（`InventoryApi` 的前缀写的是 `/v2/inventory`）。好处是子应用看到的路径
  就是客户端请求的那个——"挂载"语义下根路径会被重定向，有些协议的端点恰好在那个根上。

## 结构

```
main.py             --stage {1,2}：按阶段取一个 Server 起进程
shop/server.py      Stage1 / Stage2   ← 全部接缝
shop/legacy.py      老代码：/v1，APIRouter + Depends + 模块级状态（原样）+ create_legacy()
shop/bridge.py      老路由怎么拿到单元：app.state.graph + 一个 Depends，三行
shop/graph.py       ShopGraph（业务那一半，不认识 HTTP）+ V2Api（新模块的应用单元，path=/v2）
shop/inventory.py   InventoryApi(Router)   /v2/inventory
shop/pricing.py     PricingApi(Router) + PricingRules（纯业务单元）
shop/catalog.py     Catalog —— @start 装载、@stop 卸掉
shop/warehouse.py   Warehouse 基类 + 两个子类（基类一条默认 dep，子类各换一份配置）
shop/settings.py    三份配置：ShopSettings / PaymentSettings / WarehouseSettings ×2
shop/vault.py       PaymentSettings 的依赖
```

## 这个场景压的是什么

| 维度 | 在哪 |
|---|---|
| 我们的 `Server` 服务**别人家的**应用（原生 FastAPI 对象） | [`server.py`](shop/server.py) 阶段一 |
| 两个 ASGI 应用按路径并存在一个端口上 | 阶段二的 `dispatch` |
| 应用单元自己就是 ASGI 应用（也能交给原生服务器，lifespan 驱动图） | [boundaries](tests/test_framework_boundaries.py) |
| 老 `Depends` 路由怎么拿到图上的单元（迁移期的桥） | [`bridge.py`](shop/bridge.py) |
| 多份配置：两个前缀、两份 `.env` 文件 | [`settings.py`](shop/settings.py) |
| 配置自己有依赖与钩子 | `PaymentSettings` → `Vault` |
| 同一份配置的多个实例（子类覆盖基类那条默认 `dep()`） | [`warehouse.py`](shop/warehouse.py) |
| 测试：真实套接字跑两个阶段 + `ASGITransport` 打应用单元 + 完全不要 web 层 | [`tests/`](tests) |

## 四件做之前没想到的事

**老应用的 lifespan 一次都不会跑。** 我们的 `Server` 不向应用发 ASGI 的 lifespan 消息
（生命周期归 Canary，不该有两套）。所以"先只换服务器"这一步有个陷阱：老应用如果在
lifespan / `on_event("startup")` 里建连接池、热缓存、起后台任务，换完之后这些**悄悄地
不发生了**，而接口照样能通——直到第一个用到连接池的请求打进来。迁移时必须把老 lifespan
里的事搬成图上的单元。这一条钉在
[`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py) 里。

**桥不该是框架的事，但它被写了三遍。** 老的 `Depends` 路由要用迁过来的业务单元，这中间
需要一座桥：`app.state.graph` 放着启动好的图，一个 `Depends` 按类型取单元
（[`bridge.py`](shop/bridge.py)）。它只有三行，形状由你的老代码决定——但 `library`、
`relay`、`shop` 三个场景各写了一遍同样形状的三行，这件事值得框架那边想一想。

**`canary_framework.test.unit` 不只是测试辅助。** 桥要做的事正是"按类型从运行着的图里取回
单元"，而这就是 `unit(root, Cls)`。它放在 `canary_framework.test` 下面，所以迁移代码里写
`from canary_framework.test import unit` 看着很怪——但这确实是它该干的活。

**新模块的单元要会说"我没在运行"。** `Catalog` 在 `@start` 里装载数据、`@stop` 里卸掉，
被调用时直说"目录未装载"（落成 503），而不是返回一个空列表让调用方以为库存清零了。图和
应用同生共死，但进程里可能有别的东西还活着。

## 上一轮试出来的毛病

这个场景上一轮围绕 `mount()` 试出三条（不幂等、没有反操作、生命周期之前调它抛裸
`KeyError`），框架都修了；再后来 `mount()` 连同整个 `asgi.fastapi` 适配层一起删掉了，
所以那三条现在只剩历史意义——这一轮的迁移故事不再需要它。

这一轮新记下的一条是上面那个**老应用的 lifespan 不会被调用**：它不算 bug（设计如此），
但"先只换服务器"是最常见的迁移第一步，而这个陷阱是静默的，值得写进文档。

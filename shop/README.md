# 场景五：电商后台的渐进迁移

一个**已经在跑**的 FastAPI 电商后台。老接口在 `/v1`：模块级的 `APIRouter`、模块级的
状态、`Depends`。新模块（库存、定价）写成路由单元，用 `mount()` 挂在同一个应用上，
落在 `/v2`。两代写法在一个进程里共存，直到老的那边被逐个搬完。

和 [`relay`](../relay) / [`pipeline`](../pipeline) 的分水岭：**进程的主人是 uvicorn，
不是 Canary**。所以 `uvicorn shop.asgi:app --reload` 一点没变，生命周期由 ASGI 的
lifespan 驱动。

**这个场景只有 FastAPI 一版，没有 `asgi.web` 版**，另外三个场景都有两版。原因就是它的
主题：它讲的是"已经有一个 FastAPI 应用，怎么把新模块以路由单元的形式挂进去"——`mount()`
挂的是 FastAPI 的 `APIRouter`，老代码也是 FastAPI 的 `APIRouter` + `Depends`。
`asgi.web` 没有 `mount()`、没有 `APIRouter`，也不该有：它的应用自己就是根，不存在"挂到
别人家的应用上"这件事。要从一个老的 `asgi.web` 应用迁移，形状完全不同（那是另一个场景，
真到那一步再写）。

```bash
uv sync
uv run pytest                                      # 25 个测试
uv run python main.py                              # http://127.0.0.1:8040/docs
uv run uvicorn shop.asgi:app --reload --port 8040  # 老的启动方式照用
```

## 迁移的接缝只有四行

[`shop/asgi.py`](shop/asgi.py)：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with ShopGraph() as root:        # 启动整张图
        api = APIRouter(prefix="/v2")
        mount(root, api)                   # ← 把图上的路由单元挂进去
        app.include_router(api)
        bridge.bind(root)                  # 老路由取单元的桥
        yield
```

剩下的事一件都没动：`create_app()` 还是原来那个，`app.include_router(legacy.router)`
还在，老接口的代码一行没改。

## 结构

```
shop/asgi.py        已有的 FastAPI 应用 + lifespan 里的 mount()   ← 全部接缝
shop/legacy.py      老代码：/v1，APIRouter + Depends + 模块级状态（原样）
shop/bridge.py      老路由怎么拿到单元：use(Cls) 三行
shop/graph.py       ShopGraph —— 根单元，不认识 HTTP
shop/inventory.py   InventoryApi(Router)   /v2/inventory
shop/pricing.py     PricingApi(Router) + PricingRules（纯业务单元）
shop/catalog.py     Catalog —— @start 装载、@stop 卸掉
shop/warehouse.py   Warehouse 基类 + 两个子类（两个仓库）
shop/settings.py    三份配置：ShopSettings / PaymentSettings / WarehouseSettings ×2
shop/vault.py       PaymentSettings 的依赖
```

## 这个场景压的是什么

| 维度 | 在哪 |
|---|---|
| `mount()` 到已有 FastAPI 应用，lifespan 驱动 | [`asgi.py`](shop/asgi.py) |
| `mount()` 到 `APIRouter`（新模块落在 `/v2`） | 同上 |
| 老路由与路由单元在一个应用里共存 | [`legacy.py`](shop/legacy.py) |
| 老路由怎么拿到单元（迁移期的桥） | [`bridge.py`](shop/bridge.py) |
| 多份配置：两个前缀、两份 `.env` 文件 | [`settings.py`](shop/settings.py) |
| 配置自己有依赖与钩子 | `PaymentSettings` → `Vault` |
| 同一份配置的多个实例（子类，`model_config` 合并） | `MainWarehouseSettings` / `OverflowWarehouseSettings` |
| 测试：`lifespan_context` + `ASGITransport`，以及完全不要 web 层 | [`tests/`](tests) |

## 三件做之前没想到的事

**`mount()` 只解决路由单元，不解决老代码。** 老的 `Depends` 路由也要用迁过来的单元，
这中间需要一座桥——而桥不该是框架的事：它只有三行，形状由你的老代码决定。
[`bridge.py`](shop/bridge.py) 就是 `library` 在 0.10 时期的 `wiring.py`，那个文件在
`library` 里已经不需要了（整个换成了路由单元），但**迁移期**需要它。

**`canary_framework.test.unit` 不只是测试辅助。** 桥要做的事正是"按类型从运行着的图里
取回单元"，而这就是 `unit(root, Cls)`。它放在 `canary_framework.test` 下面，所以迁移代码
里写 `from canary_framework.test import unit` 看着很怪——但这确实是它该干的活。要么这个
函数值得一个非 test 的公开位置，要么文档该说一句"迁移期用它是对的"。

**新模块的单元要会说"我没在运行"。** `mount()` 没有反操作，所以图停了之后，应用对象上
那些路由还在。`Catalog` 因此在 `@stop` 里把数据卸掉，并在被调用时直说"目录未装载"
（落成 503），而不是返回一个空列表让调用方以为库存清零了。

## 试出来的毛病

两条写成了测试，在 [`tests/test_framework_boundaries.py`](tests/test_framework_boundaries.py)
里标着 **【毛病】**。

1. **`mount()` 不幂等，而且没有反操作。** 同一个应用对象进出 lifespan 两次，路由被挂两
   遍，**先注册的那条赢**——于是请求打在已经停掉的那张图上，返回 503，而新那张图好好的。
   唯一的外部信号是 FastAPI 重算 OpenAPI 时的一句 `Duplicate Operation ID` 警告。
   `TestClient` 复用同一个 `app`、"重启图但不重建应用"，都会掉进去。
2. **生命周期之前调 `mount()`，抛的是裸 `KeyError`。** 它从作用域的实例表里取依赖，而图
   是第一次进入生命周期时才建立的。"忘了在 lifespan 里挂"是个很常见的错误，而它得到的
   是 `KeyError: <class 'shop.inventory.InventoryApi'>`，不是读 `dep` 时那句很清楚的
   `LifecycleError: ... is unavailable before the lifecycle begins`。

还有一条和 FastAPI 版本有关，值得写进 `mount()` 的文档：

- **挂载发生在应用启动之后，所以 OpenAPI 可能停在旧的那一份上。** FastAPI 0.143 记了一个
  路由版本号，路由变了会重算，所以没事。但框架声明的下界是 `fastapi>=0.121`，而 0.121 的
  `app.openapi()` 是**无条件缓存**的（本机核对过源码）：在那个版本上，任何"启动前读一次
  schema"的动作都会让 `/openapi.json` 永久漏掉新模块。`mount()` 自己清一下
  `app.openapi_schema` 就能把这个版本差异吃掉。

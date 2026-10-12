# 场景一：智能图书馆管理系统

一个用 [Canary Framework](https://pypi.org/project/canary-framework/) **1.1**
搭的图书馆管理系统：书目与馆藏、读者、借还流通与预约队列，外加一个基于 RAG 的
智能馆员助手。

**同一份业务，两层 HTTP。** 路由与应用都是图上的单元，而"用哪个 Web 包"是可换的：

| 这一层 | 包 | 它带来什么 |
|---|---|---|
| [`app/api/fastapi/`](app/api/fastapi) | `canary_framework.asgi.fastapi` | OpenAPI、`/docs`、`tags`、FastAPI 生态 |
| [`app/api/web/`](app/api/web) | `canary_framework.asgi.web` | 只依赖 pydantic，没有 OpenAPI |

业务代码（`app/module/*/service.py`、`app/module/db/`、`app/infra/`、`config.py`）**只有
一份**，两层都不碰它。两层对外的路径、状态码、响应体一致，所以同一套行为测试对两层各跑
一遍（[`tests/conftest.py`](tests/conftest.py)），另有一条脚本逐条比对两边的答案
（[`tests/test_parity.py`](tests/test_parity.py)）。

## 快速开始

```bash
uv sync
uv run pytest                            # 216 个测试（行为测试跑两遍），零外部依赖

uv run python main.py                    # fastapi 版，:8010，带 /docs
uv run python main.py --stack web        # web 版，:8011
uv run python main.py --stack web --port 9000
```

两层默认端口不同，所以可以同时起着、用同一个脚本压。两个 `Gateway` 都带
`access_log=False`（`asgi.Server` 的类参数原样传给 `uvicorn.Config`），压测时日志不会
干扰结果。

默认配置是**零外部依赖**的：SQLite 内存库 + 离线确定性 embedding / chat 实现。
接真实的 PostgreSQL + pgvector 与 LLM，只需改 `.env`（见 `.env.example`）：

```bash
STORAGE=postgres
EMBEDDING_PROVIDER=openai
CHAT_PROVIDER=openai
LLM_API_BASE=http://localhost:4100      # litellm / DashScope compatible-mode / vLLM
```

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

## 架构

```
main.py                    --stack {fastapi,web} --port N：按名字取一个 Gateway 起进程
app/
  api/
    __init__.py            两层的注册表：application(name) / gateway(name)
    fastapi/               ← 第一层 HTTP：App + Api + 五个模块的路由单元
    web/                   ← 第二层 HTTP：同样的东西，写在 asgi.web 上
  module/
    catalog/    /api/catalog      书目与馆藏副本
    reader/     /api/readers      读者、等级、罚金
    loan/       /api/circulation  借书 / 还书 / 续借 / 预约队列
    rag/        /api/rag          文献入库、切分、向量化、语义检索
    chat/       /api/assistant    智能馆员问答（带引用）
  infra/
    db.py                  Database    唯一持有 async engine 的单元，提供 begin()/read()
    ai.py                  EmbeddingModel / ChatModel   local（离线确定性）| openai（兼容端点）
  module/db/
    models.py              9 张表：books / book_copies / readers / loans / reservations
                                  library_docs / doc_chunks / chat_sessions / chat_messages
    repository/            无状态查询对象——session 由调用方传入
```

每个模块是 `service.py`（`Canary` 单元，业务规则）+ `schema.py`（pydantic 请求/响应
模型）；路由不在模块里，而在 `app/api/<栈>/<模块>.py` —— 两层各一份，各自薄薄一层。

### 五条值得说明的设计

**接口怎么拿到单元。** 路由单元自己声明依赖，接口方法是绑定方法，直接用 `self`：

```python
class CatalogApi(Router, prefix="/catalog"):
    catalog = dep(CatalogService)

    @post("/books")
    async def create_book(self, body: CreateBookRequest) -> R[BookResponse]:
        return R.ok(await self.catalog.create_book(body))
```

两层逐行对照，差别只有四处：导入的包、`tags`（web 版没有）、成功状态码的关键字
（`status_code=` / `status=`）、领域异常的落地方式（`add_exception_handler` /
`@error(DomainError)`）。

注意作用域的粒度是**一次运行**，不是一次请求：每个类型一个实例，这正是连接池该有的
粒度。请求级的工作单元由 service 自己开。

**事务边界在 service。** repository 不开 session，方法第一个参数就是 `AsyncSession`；
service 用 `async with self.database.begin()` 包住整个用例。一次借书要同时写 `Loan`、
翻转 `BookCopy.status`、可能还要兑现 `Reservation`——这些必须同生共死。框架没有请求
作用域，所以工作单元是显式的。

**领域异常只在一处落地。** service 只 `raise`，不认识任何 HTTP 概念；每层的应用单元各有
一处把它翻成 `{code, data, msg}` 信封和对应状态码——FastAPI 版是
`app.add_exception_handler(DomainError, ...)`，web 版是 `@error(DomainError)` 标记的一个
方法。这是这次重写里少数"代码变简单了"的
地方——0.9.x 的框架删掉 `@on_request_error` 之后，领域异常必须由每个 handler 自己用
`await ok(...)` 接住，漏写一个就变成 500，只能靠代码评审兜底。

**embedding 列一次声明、两种方言。** `Vector(1024).with_variant(JSON(), "sqlite")`，
于是同一个模型在 PostgreSQL 上走 pgvector 的余弦距离算子 + HNSW 索引，在 SQLite 上
退化为 Python 内的余弦计算。测试因此不需要任何外部服务。

**助手不会瞎编。** `/api/assistant/ask` 先检索，检索为空就直接拒答，连模型都不调用；
有结果时把片段作为唯一上下文交给模型，并把 `sources`（书名、文献名、片段、相似度）
一起返回并落库。每个回答都可追溯。

## 主要接口

| 模块 | 接口 |
|---|---|
| 书目 | `POST/GET /api/catalog/books`、`GET/PATCH/DELETE /api/catalog/books/{id}`、`GET /api/catalog/categories` |
| 馆藏 | `POST/GET /api/catalog/books/{id}/copies`、`PATCH /api/catalog/copies/{id}` |
| 读者 | `POST/GET /api/readers/`、`GET/PATCH/DELETE /api/readers/{id}`、`POST /api/readers/{id}/fines/payment` |
| 流通 | `POST /api/circulation/borrow`、`/return`、`/loans/{id}/renew`、`GET /api/circulation/overdue` |
| 预约 | `POST /api/circulation/reservations`、`DELETE /api/circulation/reservations/{id}` |
| RAG | `POST/GET /api/rag/documents`、`POST /api/rag/books/{id}/index`、`GET /api/rag/search?q=` |
| 助手 | `POST /api/assistant/ask`、`POST /api/assistant/sessions/{id}/ask`、`GET .../messages` |

完整文档：以 fastapi 版启动后访问 `/docs`（Swagger UI）或 `/redoc`。web 版没有 OpenAPI，
所以也没有这两个地址——路径表只能从代码（或 `app.testing.paths_of`）读。

### 业务规则一览

- 借阅上限按读者等级：student/normal 5 册、vip 10 册、staff 20 册
- 借期同样按等级：30 / 30 / 60 / 90 天，最多续借 2 次
- 逾期每册每天 0.5 元；欠款满 20 元停借；有逾期未还时不得再借
- 全部副本借出时可预约排队；还书时自动为队首读者留存该副本 48 小时
- 有人预约时不允许续借；书目仍有在借副本时不允许注销

## 响应格式

所有接口返回 `{"code": 0, "data": ..., "msg": "ok"}`，失败时 `code` 为 404 / 409 / 422 等，
**并与 HTTP 状态行一致**（`app/testing.py::failure` 守着这条）。信封是给前端的契约，
状态码是给网关和客户端的——两样都给，只看一样也能判断结果。

请求体校验失败是唯一的例外：那由 HTTP 层在进接口之前处理，返回 pydantic 的错误列表
`{"detail": [...]}`。两层的格式几乎一样，差一个字段——FastAPI 的每条错误里多一个
`input`（被拒的那份输入），`asgi.web` 没有；`msg` 的措辞也因为 `asgi.web` 走 pydantic 的
JSON 模式而略有不同。`loc` 与 `type` 一致，所以按 `type` 做分支的客户端不受影响。
这是两层唯一的对外差异，[`tests/test_parity.py`](tests/test_parity.py) 里单独钉着。

## 测试

```bash
uv run pytest                                      # 216 passed
uv run pytest tests/test_framework_boundaries.py   # 两层各跑一遍：监听、失败回收、替换
uv run pytest tests/test_parity.py                 # 两层逐条比对同一串请求
uv run pytest tests/test_stack_web.py              # 只属于 web 那一层的规则
uv run pytest tests/test_stack_fastapi.py          # 只属于 FastAPI 那一层的东西
uv run pytest -k "[web]"                           # 只跑 web 那一遍
```

`tests/conftest.py` 的 `stack` fixture 被参数化成 `fastapi` 与 `web`，而 `client` /
`root` / `database` 都依赖它，所以**每个用到 client 的测试都会跑两遍**。

测试替换实现用框架自带的 `Scope.provide`：在生命周期开始之前
`scope_of(root).provide(AppConfig, AppConfig(...))`，整张图拿到的就是替身，真单元连构造
都不会发生。见 `tests/test_framework_boundaries.py` 的「替换」一节。

注意两个方向的区分：`Scope.provide` 是在启动前往图上**放**替身；
`canary_framework.test.unit(root, Cls)` 是从已启动的图上**取**单元（测试与迁移期的桥会
用到它，见场景五）。

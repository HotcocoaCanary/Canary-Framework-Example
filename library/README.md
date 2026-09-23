# 场景一：智能图书馆管理系统

一个用 [Canary Framework](https://pypi.org/project/canary-framework/) **1.0**
搭的图书馆管理系统：书目与馆藏、读者、借还流通与预约队列，外加一个基于 RAG 的
智能馆员助手。

**职责是分开的。** 0.10.0 删掉了 `canary_framework.web`，框架的定位收回到依赖注入与
生命周期本身，于是这两件事分给了两个库：

| | 负责什么 |
|---|---|
| **Canary** | 单元之间的依赖、构造顺序、启动与回收 |
| **FastAPI** | 路由、请求校验、状态码、OpenAPI 与 `/docs` |

两者的接触面只有 [`app/wiring.py`](app/wiring.py) 一个文件，三件事：lifespan 对接、
按类型取单元、领域异常落地。分开之后每一侧都是该领域里最普通的写法——不需要为了用
框架而学一套只在这个框架里成立的 web 约定。

## 快速开始

```bash
uv sync
uv run pytest              # 101 个测试，零外部依赖
uv run python main.py      # http://127.0.0.1:8010/docs
```

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
main.py                    uvicorn 跑 app/api.py 里的 ASGI 应用
app/
  api.py                   create_app()：FastAPI 实例 + 挂载各模块 router
  wiring.py                ← Canary 与 FastAPI 的全部接触面（lifespan / provide / 异常）
  composition.py           LibraryApi —— 组合根，依赖每个 service，但不认识 HTTP
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

每个模块是 `router.py`（FastAPI 路由）+ `service.py`（`Canary` 单元，业务规则）+
`schema.py`（pydantic 请求/响应模型）。

### 四条值得说明的设计

**handler 怎么拿到单元。** `wiring.py` 里的 `provide(Cls)` 是一个 FastAPI 依赖，
从 lifespan 启动的那张图里按类型取实例：

```python
Catalog = Annotated[CatalogService, unit(CatalogService)]

@router.post("/books")
async def create_book(body: CreateBookRequest, catalog: Catalog) -> R[BookResponse]:
    return R.ok(await catalog.create_book(body))
```

注意作用域的粒度是**一次运行**，不是一次请求：每个类型一个实例，这正是连接池该有的
粒度。请求级的工作单元由 service 自己开。

**事务边界在 service。** repository 不开 session，方法第一个参数就是 `AsyncSession`；
service 用 `async with self.database.begin()` 包住整个用例。一次借书要同时写 `Loan`、
翻转 `BookCopy.status`、可能还要兑现 `Reservation`——这些必须同生共死。框架没有请求
作用域，所以工作单元是显式的。

**领域异常只在一处落地。** service 只 `raise`，不认识任何 HTTP 概念；
`wiring.py::install_error_handlers` 用一个 `@app.exception_handler(DomainError)`
把它翻成 `{code, data, msg}` 信封和对应状态码。这是这次重写里少数"代码变简单了"的
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

完整文档：启动后访问 `/docs`（Swagger UI）或 `/redoc`。

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

请求体校验失败是唯一的例外：那由 FastAPI 在进 handler 之前处理，返回它自己的 422 格式。

## 测试

```bash
uv run pytest                                      # 101 passed
uv run pytest tests/test_framework_boundaries.py   # 21 条：Canary ↔ FastAPI 接缝
```

测试替换实现用框架自带的 `Scope.provide`：在生命周期开始之前
`scope_of(root).provide(AppConfig, AppConfig(...))`，整张图拿到的就是替身，真单元连构造
都不会发生。见 `tests/test_framework_boundaries.py` 的「替换」一节。

注意与 `app/wiring.py` 里的 `provide(Cls)` 区分：那是给 FastAPI handler 用的依赖函数，
从已启动的图上**取**单元；`Scope.provide` 是在启动前往图上**放**替身。

# 智能图书馆管理系统

一个用 [Canary Framework](https://pypi.org/project/canary-framework/) **0.9.3**
（`release/0.9.3` @ `fb712de`）从头搭建的
图书馆管理系统：书目与馆藏、读者、借还流通与预约队列，外加一个基于 RAG 的智能馆员助手。

全栈只用框架提供的东西：`@cocoa`（最小单元 + 依赖注入）、生命周期钩子
（`@on_start` / `@on_stop`）、`@web_cocoa` + `@get/@post/...`（HTTP 路由，含
`status_code` / `tags` / `summary`）。框架的公开面就这么大——组装只有
`Canary(LibraryApi)` 一句，没有替换入口，也没有异常映射登记：领域异常由应用自己
在 `app/common/errors.py::ok` 接住。
过程中遇到的框架问题记录在 [`../../doc/bug/`](../../doc/bug/)，汇总见
[`../../doc/verification-final.md`](../../doc/verification-final.md)。

## 快速开始

```bash
uv sync
uv run pytest              # 105 个测试，零外部依赖
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
main.py                Canary(LibraryApi) —— Canary 本身就是 ASGI 应用
└── app/api.py         LibraryApi  @web_cocoa(prefix="/api")  ← 组合根，也是 OpenAPI 元数据来源
    ├── catalog/       /api/catalog      书目与馆藏副本
    ├── reader/        /api/readers      读者、等级、罚金
    ├── loan/          /api/circulation  借书 / 还书 / 续借 / 预约队列
    ├── rag/           /api/rag          文献入库、切分、向量化、语义检索
    └── chat/          /api/assistant    智能馆员问答（带引用）

app/infra/
    db.py              Database    唯一持有 async engine 的单元，提供工作单元 begin()/read()
    ai.py              EmbeddingModel / ChatModel   local（离线确定性）| openai（兼容端点）

app/module/db/
    models.py          9 张表：books / book_copies / readers / loans / reservations
                             library_docs / doc_chunks / chat_sessions / chat_messages
    repository/        无状态查询对象——session 由调用方传入
```

### 三条值得说明的设计

**事务边界在 service。** repository 不开 session，方法第一个参数就是
`AsyncSession`；service 用 `async with self.database.begin()` 包住整个用例。
一次借书要同时写 `Loan`、翻转 `BookCopy.status`、可能还要兑现 `Reservation`——
这些必须同生共死。框架没有请求作用域，所以工作单元是显式的
（[bug/009](../../doc/bug/009-no-request-scope-or-unit-of-work.md)）。

**embedding 列一次声明、两种方言。** `Vector(1024).with_variant(JSON(), "sqlite")`，
于是同一个模型在 PostgreSQL 上走 pgvector 的余弦距离算子 + HNSW 索引，
在 SQLite 上退化为 Python 内的余弦计算。测试因此不需要任何外部服务。

**助手不会瞎编。** `/api/assistant/ask` 先检索，检索为空就直接拒答，
连模型都不调用；有结果时把片段作为唯一上下文交给模型，并把
`sources`（书名、文献名、片段、相似度）一起返回并落库。每个回答都可追溯。

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

所有接口返回 `{"code": 0, "data": ..., "msg": "ok"}`，失败时 `code` 为 404 / 409 / 422 等。

信封是给前端的契约，**状态码从 0.9.3 起回到了状态行上**：领域异常由
`LibraryApi` 上的两个 `@on_request_error` 映射成真实的 HTTP 状态，
`code` 与 `status` 始终一致（`app/testing.py::failure` 守着这条）。
0.9.2 时框架只会构造 200 的 `JSONResponse`，那才是 `code` 当初存在的原因。

## 测试

```bash
uv run pytest                                   # 102 passed
uv run pytest tests/test_framework_boundaries.py   # 框架边界的可执行说明
```

`tests/test_framework_boundaries.py` 里每个测试都钉住一条框架行为，并注明它逼出了
本项目的哪个设计。已修复的能力从正面钉住（回归保护），仍然坏掉的从反面钉住
（标了 `STILL BROKEN`）。**框架再修好一处，对应的测试就会失败**，
正好提示对应的绕行代码可以删掉。

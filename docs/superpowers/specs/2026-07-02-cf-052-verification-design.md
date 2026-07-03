# Canary-Agent 的 canary-framework 0.5.2 适配验证与 bug 报告 — 设计规格

日期：2026-07-02
状态：已批准（用户确认范围为「仅适配验证 + bug 报告」，验证方案选定 pytest 套件）

## 1. 背景

- 项目已升级到 canary-framework 0.5.2（`.venv` 中已安装，pyproject.toml 已声明 `>=0.5.2`）。
- 0.5.2 的核心变更（见 `doc/zh/whats-new.md`）：Router 重设计为单点记忆化组装、只支持显式前缀、
  路径冲突抛 `ValueError`、新增公开方法 `ServiceBase.openapi()`、5 项请求处理缺陷修复。
- 探索阶段已确认：三个 Router（`/kb`、`/file`、`/coll`）都有显式 prefix，代码没有引用已删除的旧机制，
  `AppModule().init()` + `asgi_app` + `openapi()` 装配冒烟测试通过，11 条路由无冲突。
- 框架是用户本人开发的，可能有 bug；发现的框架/文档 bug 需要以 issue 形式记录。

## 2. 目标与边界

**目标：**

1. 系统性验证本项目在 cf 0.5.2 下的行为（装配层 + 请求管线），留下可重复执行的回归测试套件。
2. 将验证中发现的**框架 bug 与文档错误**以 issue 形式写入 `doc/bug/`。
3. 对框架的功能期望（验证中自然产生的）写入 `doc/fet/`。
4. 产出验证报告，汇总验证矩阵结果与应用层遗留问题。

**边界（明确不做）：**

- 不修改任何应用代码。应用层问题只记录，不修复，包括已发现的：
  - `app/module/kb/router.py` `list_public` 的 `keyword` 参数未在路径字符串中声明（`?keyword={keyword}`），
    按 0.5.2 语义永远不会从查询串绑定；
  - `app/module/kb/router.py` 路径拼写错误 `/dalete`；
  - langgraph 在依赖中但代码完全未使用；pydantic-ai 尚未引入；
  - `app/shared/coze/service.py` 是空壳且类名 `KbService` 与 `app/module/kb/service.py` 重名。
- 不搭建 agent/聊天模块（留待下一轮）。
- 不做数据库层 e2e（DB 行为与 cf 适配无关）。

## 3. 测试套件结构

```
tests/
├── conftest.py               # fixture：装配 AppModule + Starlette TestClient
├── test_assembly.py          # 装配层：路由表、显式前缀、docs 三端点、openapi() 记忆化
├── test_request_pipeline.py  # 请求管线：对本项目真实端点的绑定行为
└── test_cf_behavior.py       # 框架级玩具复现：与本项目解耦的 cf 行为验证
```

设计要点：

- **不需要数据库**：service 层捕获异常返回 `R.fail`，请求能到达 handler 即证明路由匹配与参数绑定正确。
- 本项目端点覆盖不到的行为（bool query 解析、缺失必填 query→422、`(body, status_code)` 元组、
  路由冲突→`ValueError`）用 `test_cf_behavior.py` 中的玩具 service 验证；这些玩具代码同时作为
  bug 报告的最小复现。
- **风险点**：cf 的 `@service()` 可能使用全局注册表。实现的第一步是确认在测试中定义玩具 service
  是否会污染 `AppModule` 的装配；若有污染，用进程隔离（pytest-forked 或分文件收集）或 fixture 清理。
- 依赖：仅新增 `pytest` 到 dev 依赖组（TestClient 所需的 httpx 已在依赖中）。
- 全部测试通过 `uv run pytest` 可重复执行。

## 4. 验证矩阵

| # | 0.5.2 变更点 | 验证方式 |
|---|---|---|
| 1 | 显式前缀（无 `/{ServiceName}` 自动命名空间） | 真实端点：11 条路径与各自 prefix 拼接一致 |
| 2 | 路径冲突 → 组装时抛 `ValueError` | 玩具复现：两个无前缀 service 相同路径 |
| 3 | `openapi()` 公开方法 + 记忆化 | 真实 app 调用两次，比对结果一致性 |
| 4 | path 参数 + 请求体同存（按名绑定，不再 500） | 真实端点 `PATCH /kb/{kb_id}/update` |
| 5 | 缺失必填 query → 422（此前 500） | 玩具复现（本项目 query 均有默认值，覆盖不到） |
| 6 | bool query 解析（`1/true/yes/on` 等，非法值 422） | 玩具复现 |
| 7 | `(body, status_code)` 元组正确设置状态码 | 玩具复现 |
| 8 | OpenAPI schema 注册表不再进程级泄漏（无悬空 `$ref`） | 真实 app 重复生成两次，校验所有 `$ref` 可解析 |
| 9 | `{param:path}` 转换器路由 | 真实端点 `/file/{kb_id}/{folder_path:path}` 路由匹配 + OpenAPI 路径合法性（预期暴露 bug） |
| 10 | docs 三端点 | `GET /docs`、`/redoc`、`/openapi.json` 均 200 |

## 5. 文档审计

将 `doc/zh` 全部 11 篇与 `.venv` 中已安装的 0.5.2 源码逐一核对：import 路径、方法签名（同步/异步）、
构造参数、示例可运行性。

已立案的差异（待写入 doc/bug）：

1. **OpenAPI 路径泄漏 Starlette 转换器语法**：`openapi()` 输出的 paths 中出现
   `/file/{kb_id}/{folder_path:path}`；OpenAPI 3.0.3 的 path template 不允许 `:path` 后缀，
   应剥离为 `{folder_path}`。（框架 bug）
2. **`lifecycle.md` / `configuration.md` 示例写 `await app.init()`**：实际 0.5.2 中
   `ModuleBase.init()` / `ServiceBase.init()` 是同步方法（`startup()`/`shutdown()` 才是异步）。（文档 bug）
3. **`dependency-injection.md` 引用 `canary_framework.engine.injector`**：实际模块为
   `canary_framework.engine.dependencies`（`resolve_deps`、`topological_sort` 从
   `canary_framework.engine` 导出）。（文档 bug）

## 6. 产出物与格式

| 产出物 | 位置 | 格式 |
|---|---|---|
| bug 报告 | `doc/bug/NNN-<slug>.md` | 中文 issue 风格：标题 / 影响版本 / 最小复现代码 / 期望 vs 实际 / 疑似原因（定位到 cf 源码文件） |
| 功能期望 | `doc/fet/NNN-<slug>.md` | 中文：动机 / 期望 API / 与现有设计理念的契合度；只写验证中自然产生的，不硬凑 |
| 验证报告 | `doc/verification-0.5.2.md` | 验证矩阵结果总表 + 应用层遗留问题清单（标注「超出本轮范围」） |
| 回归测试 | `tests/` | pytest，`uv run pytest` 可重复执行 |

## 7. 错误处理与测试策略

- 测试不依赖网络与数据库；`QwenService` 构造 OpenAI client 不发请求，空 api_key 不影响（冒烟已验证）。
- 玩具复现与真实 app 测试分文件，避免注册表交叉污染；实现首步先验证隔离性。
- 每个疑似框架 bug 必须先做脱离本项目的最小复现，确认后才写入 `doc/bug`；复现失败则降级为应用层问题记录。
- 文档 bug 以「文档 vs 源码」双方引用为证据（文件 + 行为差异），不猜测。

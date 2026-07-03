# Canary-Agent × canary-framework 0.5.2 适配验证报告

日期：2026-07-03
测试命令：`uv run pytest`
结果：**26 passed, 5 xfailed**（5 个 xfail 全部对应在案 bug，strict 模式——框架修复后会转为 FAIL 提醒移除标记）

## 结论

Canary-Agent 与 cf 0.5.2 **基本兼容**：显式前缀迁移在先前提交中已完成，装配、DI、
docs 端点、`/kb`、`/coll` 模块全部正常。**唯一的实际破坏点**：`/file` 模块的全部
4 个端点因框架不支持 `{param:path}` 转换器语法（doc/bug/001）在运行时 500，等待框架
修复即可自动恢复（应用代码无需改动）。

本轮共立案 **框架 bug 2 个**（001、002）、**文档 bug 3 个**（003、004、005）、
**功能期望 2 个**（fet-001、fet-002）。

## 验证矩阵结果

| # | 0.5.2 变更点 | 结果 | 测试位置 |
|---|---|---|---|
| 1 | 显式前缀（无 `/{ServiceName}` 命名空间） | ✅ 通过 | `test_assembly.py::test_explicit_prefix_paths` / `test_no_service_name_namespace` |
| 2 | 路径冲突 → 组装时抛 `ValueError` | ✅ 通过 | `test_cf_behavior.py::test_route_collision_raises_value_error` |
| 3 | `openapi()` 公开方法 + 记忆化 | ✅ 通过 | `test_assembly.py::test_openapi_public_and_memoized` |
| 4 | path 参数 + 请求体同存不再 500 | ✅ 通过 | `test_request_pipeline.py::test_path_param_plus_body_patch` |
| 5 | 缺失必填 query → 422 | ✅ 通过 | `test_cf_behavior.py::test_missing_required_query_is_422` |
| 6 | bool query 解析（8 种值 + 非法值 422） | ✅ 通过 | `test_cf_behavior.py::test_bool_query_parsing` / `test_bool_query_invalid_is_422` |
| 7 | `(body, status_code)` 元组设置状态码 | ✅ 通过 | `test_cf_behavior.py::test_tuple_return_sets_status_code` |
| 8 | OpenAPI 无悬空 `$ref` | ✅ 通过 | `test_assembly.py::test_openapi_refs_resolvable` |
| 9 | `{param:path}` 转换器路由 | ❌ **doc/bug/001**（绑定 500 + OpenAPI 泄漏 + 参数缺失） | `test_cf_behavior.py::test_path_converter_param_binds`、`test_request_pipeline.py::test_path_converter_*`、`test_assembly.py::test_openapi_paths_are_valid_openapi_templates`（均 strict xfail） |
| 10 | docs 三端点（/docs /redoc /openapi.json） | ✅ 通过 | `test_assembly.py::test_docs_endpoints` |

矩阵之外验证的文档语义：带默认值但未在路径字符串声明的参数永不从查询串绑定
（`test_cf_behavior.py::test_undeclared_query_param_keeps_default`，通过）；`dict` 请求体
参数不绑定（**doc/bug/002**，`test_cf_behavior.py::test_dict_body_param_binds`，strict xfail）。

## bug 与功能期望索引

| 文件 | 一句话摘要 |
|---|---|
| `doc/bug/001-path-converter-params-unsupported.md` | 框架：`{param:converter}` 路径参数端到端不支持（根因 `_PARAM_PATTERN` 不匹配冒号），/file 模块全部端点 500 |
| `doc/bug/002-dict-body-param-unbound.md` | 框架：`dict` 请求体参数（无显式 request_model）不绑定 → TypeError 500，与 web.md 示例矛盾 |
| `doc/bug/003-docs-await-init-mismatch.md` | 文档：8/11 篇写 `await app.init()` 但 init() 同步；且 `async def init` 覆写会静默不执行（已实测） |
| `doc/bug/004-docs-engine-injector-path.md` | 文档：`engine.injector` 模块不存在，实际是 `engine.dependencies` |
| `doc/bug/005-docs-config-host-port-fields.md` | 文档：CanaryConfig 字段表含不存在的 `host`/`port` |
| `doc/fet/001-structured-error-responses.md` | 期望：handler 异常的结构化 JSON 兜底 + 可注册异常映射 |
| `doc/fet/002-config-driven-server-run.md` | 期望：`app.run()` 消费 config 的 host/port |

## 文档审计汇总（doc/zh 全部 11 篇 vs 0.5.2 安装包）

- 82 条 `canary_framework` import 全量执行，仅 `engine.injector` 2 条失败（→ bug 004）。
- `CanaryConfig` 除 `host`/`port` 外，12 个字段的名称与默认值逐一吻合（→ bug 005）。
- core.md 的内部名（`_cf_collect_routes`、`_cf_assemble`、`Assembled`、`ResolvedRoute`）均存在；
  `@service()`/`@module()`/`@config()` 签名、`ServiceEntry` 字段、`LifecycleHookError` import 与文档一致。
- whats-new.md 的 5 项修复全部经测试验证成立。

## 应用层遗留问题（超出本轮范围，未修改代码）

1. **`app/module/kb/router.py` `list_public`**：`keyword` 参数未在路径字符串声明，永不从查询串绑定
   （语义已被 `test_undeclared_query_param_keeps_default` 证实）。修复：路径改为
   `'/public/list?page={page}&size={size}&keyword={keyword}'`。
2. **`app/module/kb/router.py`**：路径拼写错误 `'/{kb_id}/dalete'`（应为 delete）。对外 API 路径，
   修复属破坏性变更，需要决定时机。
3. **依赖清理**：`langgraph` 在 pyproject 中声明但代码零引用；建议下一轮移除，并按项目方向引入
   `pydantic-ai` 搭建 agent 模块（Session/Message 模型已就位）。
4. **`app/shared/coze/service.py`**：空壳实现且类名 `KbService` 与 `app/module/kb/service.py::KbService`
   重名（未注册进任何 module，暂无实害）。
5. **`app/module/db/repository/*`**：同步 `create_engine` 配 `postgresql+asyncpg` URL，
   sync/async 驱动不匹配，真实连接数据库时会失败（本轮无 DB 未触发）；建议统一为
   `create_async_engine` + async session，或换同步驱动。

## xfail 语义说明

5 个 xfail 均为 `strict=True`：它们断言的是**文档承诺的正确行为**。canary-framework 修复对应
bug 后，这些测试会变成 XPASS→FAIL，提醒移除标记——即 bug 修复的回归确认是自动的。

# Canary-Agent × canary-framework 0.5.2 适配验证报告

日期：2026-07-03
测试命令：`uv run pytest`
结果：**31 passed, 1 xfailed**（唯一的 xfail 对应 doc/bug/002，strict 模式——框架修复后会转为 FAIL 提醒移除标记）

## 结论

Canary-Agent 与 cf 0.5.2 **兼容**：显式前缀迁移在先前提交中已完成，装配、DI、
docs 端点、`/kb`、`/coll`、`/file` 模块全部正常。

`/file` 模块原先使用 `{folder_path:path}` 转换器语法，运行时因 cf 不解析 Starlette 转换器
（见下方「已知框架限制」）而 500。本轮经与框架作者确认，这是 cf 的**设计选择而非缺陷**——
遂在**应用侧改用查询参数** `?folder_path=...` 规避（查询值允许含斜杠），4 个端点已全部恢复，
且 OpenAPI 路径变为合法 template。此改动是本轮唯一的应用代码变更。

本轮共立案 **文档/框架 bug 4 个**（doc/bug/002 dict 请求体；003/004/005 文档）、
**功能期望 2 个**（fet-001、fet-002）。原 doc/bug/001（`:path` 转换器）已撤回，改为上述应用侧规避。

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
| 9 | 多级路径参数 | ✅ 通过（应用侧改用查询参数 `?folder_path=`，非 `:path` 转换器） | `test_request_pipeline.py::test_file_list_with_folder_query` / `test_file_list_root_default` / `test_file_delete_with_folder_query` / `test_file_delete_missing_folder_is_422`；`test_assembly.py::test_openapi_paths_are_valid_openapi_templates` |
| 10 | docs 三端点（/docs /redoc /openapi.json） | ✅ 通过 | `test_assembly.py::test_docs_endpoints` |

矩阵之外验证的文档语义：带默认值但未在路径字符串声明的参数永不从查询串绑定
（`test_cf_behavior.py::test_undeclared_query_param_keeps_default`，通过）；`dict` 请求体
参数不绑定（**doc/bug/002**，`test_cf_behavior.py::test_dict_body_param_binds`，strict xfail）。

## 已知框架限制（设计选择，非 bug）

cf 在 `core/router/_utils.py` 用 `_PARAM_PATTERN = r"\{(\w+)\}"` 解析路径参数名，**不识别
Starlette 转换器语法**（`{x:path}`、`{x:int}`、`{x:uuid}` 等）。虽然 cf 把完整路径原样交给
Starlette 的 `Route()`、Starlette 也能匹配并填充 `request.path_params`，但 cf 的绑定循环只遍历
自己解析出的参数名，因此转换器参数不会被回读（运行时缺参 500，OpenAPI 也不含该参数）。

**应对**：应用层避免使用转换器语法，改用查询参数承载（查询值允许含斜杠，可表达多级路径）。
`/file` 模块即据此从 `{folder_path:path}` 改为 `?folder_path={folder_path}`。

## bug 与功能期望索引

| 文件 | 一句话摘要 |
|---|---|
| ~~doc/bug/001~~ | 已撤回：`{param:path}` 转换器不被支持，经确认为设计选择；改为应用侧查询参数规避（见「已知框架限制」） |
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

## 本轮已处理的应用代码变更

- **`app/module/file/router.py`**：4 个端点从 `{folder_path:path}` 改为查询参数
  `?folder_path={folder_path}`（列表可选默认根目录，其余必填），规避 cf 转换器限制。
  这是本轮唯一的应用代码改动，已有 `test_request_pipeline.py` 的 4 个新测试覆盖。

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

唯一的 xfail（`test_dict_body_param_binds`，对应 doc/bug/002）为 `strict=True`：它断言的是
**web.md 文档承诺的正确行为**。canary-framework 修复该 bug（或修正文档并让缺参转为结构化错误）
后，该测试会变成 XPASS→FAIL，提醒移除标记——即 bug 修复的回归确认是自动的。

# Canary-Agent × canary-framework 0.9.1 验证报告

日期：2026-08-18
测试命令：`uv run pytest`
结果：**31 passed**（0 warning 与路由自省相关；2 个 warning 为应用自身的 `datetime.utcnow()` 用法，与框架无关）

## 结论

0.9.1 修复了 `doc/canary-framework-0.9-migration-feedback.md` 中记录的两个 P0/环境类问题，
均已在本仓库实测验证通过，相关的临时绕过代码已移除：

| # | 0.9.0 反馈的问题 | 0.9.1 CHANGELOG 声明的修复 | 本次验证 |
|---|---|---|---|
| 1 | Router/hook 自省按方法名去重，导致 mixin 同名方法互相覆盖丢路由；`getattr(instance, name)` 触发 Pydantic 弃用告警 | `routes_of`/`hooks_of` 改为按类 `__dict__` + 函数身份去重 | ✅ 通过——见「验证 1」 |
| 2 | Starlette 1.x `TestClient` 依赖 `httpx2`，环境缺失导致请求挂起，被迫改用 `httpx.ASGITransport` 绕过 | 新增可选依赖 `canary-framework[test]`（`httpx2>=2.10`） | ✅ 通过——见「验证 2」 |

3.2（缺配置扩展）、3.3（版本迁移成本）两项是架构建议，0.9.1 未涉及，仍然按反馈文档现状处理。

## 验证 1：mixin 同名路由不再互相覆盖

`AppApi(KBRouter, FileRouter, CollRouter)` 中三个 mixin 各自都有一个 `create` 方法。
0.9.0 时被迫把其中两个改名为 `create_coll`/`create_file` 才能绕过丢路由问题。

本次改动：

- 恢复三个 router 的方法名统一为 `create`（`app/module/collection/router.py`、
  `app/module/file/router.py`；`app/module/kb/router.py` 本就叫 `create`，未改）。
- 独立复现脚本验证 `routes_of` 按函数身份去重后，三个同名 `create` 各自绑定到正确的类：

  ```
  POST /coll/create <bound method CollRouter.create ...>
  POST /file/{kb_id} <bound method FileRouter.create ...>
  POST /kb/create <bound method KBRouter.create ...>
  ```

- `python -W error::DeprecationWarning` 跑一次真实请求（`GET /kb/create`），确认路由收集
  过程不再触发 Pydantic `model_fields` 等实例属性弃用告警。
- 全量测试（含 `test_assembly.py` 的 11 条路径断言、`test_request_pipeline.py` 的参数绑定
  用例）31 项全部通过。

## 验证 2：官方 `TestClient` 可直接使用

按 `docs/zh/web.md` 的建议，给 `canary-framework` 加 `[test]` extra（拉入 `httpx2`），
把测试客户端从手写的 `httpx.ASGITransport` 包装类换回官方
`starlette.testclient.TestClient(AppModule())`（以 `with` 语句驱动 lifespan，
`init()`/`start()` 由框架自动触发）：

- `pyproject.toml`：`dev` 依赖组新增 `canary-framework[test]>=0.9.1`。
- `tests/conftest.py`：`client` fixture 改为 `with TestClient(AppModule()) as test_client: yield test_client`。
- `tests/test_cf_behavior.py`：`toy_client` 同步改为 `TestClient(Canary(Toy))`，删除手写
  `Client` 包装类和多余的 `toy_app` fixture。

`uv sync` 后 `httpx2` 正常安装，`TestClient` 请求不再挂起，31 项测试全部通过。

## 结论对反馈文档的影响

`doc/canary-framework-0.9-migration-feedback.md` § 5「本次迁移为绕过问题做的临时处理」
中的前两条（router 同名方法改名、测试客户端改用 ASGITransport）已随 0.9.1 失效并在本仓库
移除；第三条（`folder_path` 用查询参数而非路径转换器）与本次修复无关，予以保留。

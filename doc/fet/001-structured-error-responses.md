# fet-001：handler 异常的结构化错误响应兜底层

- **提出背景**：Canary-Agent 的 cf 0.5.2 适配验证（2026-07）
- **关联**：doc/bug/001、doc/bug/002 的失败形态都放大了本期望的必要性

## 动机

验证中观察到：handler 内任何未处理异常（例如 bug 001/002 的参数缺失 TypeError）会直接
逃出 ASGI 应用——没有兜底 500 响应层。后果：

- 客户端可能收到连接中断而非 HTTP 响应（取决于 ASGI 服务器的容错）；
- 测试里必须 `TestClient(..., raise_server_exceptions=False)` 才能拿到 500；
- 生产环境的错误形态是裸 traceback，不是稳定的 JSON 错误契约。

商业 API 需要在任何情况下都返回结构良好的错误（如 `{"code": 500, "msg": "internal error"}`），
本项目目前只能靠在每个 service 方法里手工 try/except 包一层 `R.fail` 来模拟，模板代码多且容易漏。

## 期望行为

1. **框架兜底**：请求处理管线最外层捕获所有未处理异常 → 结构化 JSON 500（不泄漏栈信息，
   栈进 `cf` 日志），保证「任何请求必有 JSON 响应」。
2. **可注册的异常映射**（进阶）：允许应用按异常类型注册 handler，风格与 cf 现有装饰器一致，例如：

```python
@service()
class Api(ServiceBase):
    router = Router(prefix="/api")

    @router.error_handler(DomainError)
    async def on_domain_error(self, exc: DomainError):
        return {"code": exc.code, "msg": str(exc)}, 400
```

## 与设计理念的契合

- 与 0.5.2「路径冲突是真正的报错」同一哲学：错误显式、可观测、不静默；
- 请求侧已有 400/422 的强类型校验契约，响应侧补上对等契约后，
  「强类型进、强类型出」才算闭环——这也是选择 pydantic 系技术栈的初衷。

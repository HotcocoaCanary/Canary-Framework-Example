# 005：configuration.md 字段表包含实际不存在的 `host` / `port` 字段

- **类型**：文档 bug
- **影响版本**：canary-framework 0.5.2 文档
- **发现方式**：Canary-Agent 适配验证的文档审计（`CanaryConfig.model_fields` 与文档字段表逐项比对）

## 证据

`doc/zh/configuration.md` 的「CanaryConfig」字段表声称：

| 字段 | 类型 | 默认值 |
|---|---|---|
| `host` | `str` | `"127.0.0.1"` |
| `port` | `int` | `8000`（1-65535） |

并在「服务器」一节展开描述。实测（0.5.2 安装包）：

```python
from canary_framework.common.config import CanaryConfig
set(CanaryConfig.model_fields)
# {'log_level', 'openapi_title', 'openapi_version', 'openapi_description',
#  'openapi_servers', 'openapi_security_schemes', 'docs_openapi_path',
#  'docs_swagger_path', 'docs_redoc_path', 'docs_swagger_css_cdn',
#  'docs_swagger_js_cdn', 'docs_redoc_cdn'}
CanaryConfig().host
# AttributeError: 'CanaryConfig' object has no attribute 'host'
```

其余 12 个字段的名称与默认值与文档**逐一吻合**，仅 `host`/`port` 不存在。

## 期望 vs 实际

- **期望**：字段表与 `canary_framework/common/config.py` 一致。
- **实际**：`host`/`port` 不是框架字段。文档示例 `@config() class AppConfig(CanaryConfig): host: str = "0.0.0.0"` 能跑通，只是因为 pydantic 允许子类自定义字段——框架本身不消费它们（服务器绑定地址/端口由 `uvicorn.run(host=..., port=...)` 决定，与 config 无关）。lifecycle.md「ASGI 生命周期」示例同样把 host/port 写进 config，有相同的误导。

## 修复建议

二选一：

1. **文档侧**：字段表删去 `host`/`port` 及「服务器」小节，或明确标注“这只是自定义字段惯例，框架不消费”；
2. **框架侧**：让框架真正支持 `host`/`port`（例如提供 `app.run()` 读取 config 启动 uvicorn）——若采纳，见 doc/fet 的相关期望。

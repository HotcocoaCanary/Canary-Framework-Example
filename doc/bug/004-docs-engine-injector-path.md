# 004：dependency-injection.md 引用不存在的 `canary_framework.engine.injector` 模块

- **类型**：文档 bug
- **影响版本**：canary-framework 0.5.2 文档
- **发现方式**：Canary-Agent 适配验证的文档 import 审计（82 条 import 全量 exec，仅此 2 条失败）

## 证据

`doc/zh/dependency-injection.md`「手动注入」与「拓扑排序」两节：

```python
from canary_framework.engine.injector import topological_sort, resolve_deps
# ModuleNotFoundError: No module named 'canary_framework.engine.injector'
```

实际位置（0.5.2 安装包实测）：

```python
from canary_framework.engine.dependencies import resolve_deps, topological_sort  # 真实模块
from canary_framework.engine import resolve_deps, topological_sort               # 亦从包级再导出
```

## 期望 vs 实际

- **期望**：文档 import 路径可直接运行。
- **实际**：`engine.injector` 不存在，两处示例均 `ModuleNotFoundError`。

## 修复建议

文档中两处 `canary_framework.engine.injector` 改为 `canary_framework.engine.dependencies`
（或推荐更稳定的包级导入 `from canary_framework.engine import ...`）。

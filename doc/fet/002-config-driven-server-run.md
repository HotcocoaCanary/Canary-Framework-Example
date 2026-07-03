# fet-002：配置驱动的服务器启动（`app.run()` 消费 host/port）

- **提出背景**：Canary-Agent 的 cf 0.5.2 适配验证（2026-07）
- **关联**：doc/bug/005（configuration.md 声称存在 host/port 字段，实际框架不消费）

## 动机

configuration.md 把 `host`/`port` 写进了 CanaryConfig 字段表（实际不存在，见 doc/bug/005），
说明「配置里声明服务器地址」本来就是文档作者（也是框架作者）的直觉预期。目前每个入口
文件都要手写：

```python
app = AppModule()
app.init()
uvicorn.run(app, host="0.0.0.0", port=8010, lifespan="on")
```

host/port 散落在代码里而非配置里，与「Config 是普通的 DI 服务」的理念相悖——
其它一切都能从 `.env` 注入，唯独绑定地址不行。

## 期望行为

`CanaryConfig` 真正提供 `host`/`port` 字段（文档表里的默认值即可），并新增：

```python
app = AppModule()
app.run()   # 等价于 app.init() + uvicorn.run(app, host=cfg.host, port=cfg.port, lifespan="on")
```

`run()` 只是薄封装，`init()` + 手动 uvicorn 的旧路径保持可用（渐进、不破坏）。

## 与设计理念的契合

- 补全 bug 005 修复方向 2：让文档与实现在「支持」侧收敛，而非删文档；
- 配置集中化与 12-factor 一致，对 Docker 部署（本项目 Dockerfile 即 `python main.py`）尤其顺手。

# Contributing / 贡献指南

本仓库用两个形态不同的真实项目演示 [Canary Framework](https://github.com/HotcocoaCanary/Canary-Framework)
的用法。欢迎修正、改进示例，或补充新的场景。
This repository demonstrates Canary Framework with two deliberately different projects.
Fixes, improvements and new scenarios are welcome.

框架本身的问题、新 API 的提议请到[主仓库](https://github.com/HotcocoaCanary/Canary-Framework)；
示例只使用框架已发布的公开 API。
Framework issues and API proposals belong in the main repository; examples use only the
framework's released public API.

## 环境搭建 / Development setup

两个示例各是一个独立的 uv 工程 / Each example is a standalone uv project:

```bash
git clone https://github.com/HotcocoaCanary/Canary-Framework-Example.git
cd Canary-Framework-Example/library     # 或 / or telemetry
uv sync
uv run pytest
uvx ruff@0.15.15 check .
```

## 流程 / Workflow

与主仓库一致 / Same as the main repository:

- 从 `main` 创建分支，通过 PR 合并；只使用 squash 合并，CI 须全部通过。
  Branch from `main` and merge through pull requests; squash merge only, after CI passes.
- **PR 标题即 main 上的提交信息**，遵循 Conventional Commits，例如
  `fix(library): 借阅超期计算`、`docs(telemetry): 补充告警去重说明`。
  **The PR title becomes the commit message on `main`** and follows Conventional Commits.
- 行为或写法变化时同步更新对应的 README。
  Update the matching README when behaviour or idioms change.

## 跟随框架升级 / Following framework releases

Dependabot 每周检查 `canary-framework` 的新版本并开 PR；CI 每周还会用框架 `main` 分支的代码
跑一遍测试，提前发现即将到来的不兼容。
Dependabot opens a weekly PR for new `canary-framework` releases, and CI runs the tests
against the framework's `main` branch every week to catch upcoming incompatibilities early.

## 许可证 / License

贡献的代码将采用 Apache 2.0 许可证。
Contributions are licensed under Apache 2.0.

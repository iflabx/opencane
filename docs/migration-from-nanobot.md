# 从 nanobot 到 OpenCane 的文档迁移说明

## 本次调整内容

1. 根目录原有 nanobot 文档全部归档到 `local-docs/nanobot-legacy/`
2. 重建 OpenCane 文档体系，统一入口为根目录 `README.md` 和 `docs/README.md`
3. 文档结构从“历史演进 + 分散专题”调整为“产品化结构 + API/运维可执行手册”

## 命名与兼容

- 项目名称：OpenCane
- 代码包名：`nanobot`（暂未改包名）
- CLI 命令：`nanobot`（暂未改命令）
- 配置目录：`~/.nanobot`（暂未迁移）

这意味着：

- 文档中的项目术语统一为 OpenCane
- 具体执行命令仍使用 `nanobot ...`

## 迁移后的文档分层

- 产品层：`docs/overview.md`
- 上手层：`docs/quickstart.md`
- 设计层：`docs/architecture.md`, `docs/data-flow.md`
- 接口层：`docs/api/*.md`
- 运行层：`docs/deployment-config.md`, `docs/operations-runbook.md`, `docs/security.md`
- 规划层：`docs/roadmap.md`

## 对历史文档的处理策略

- 历史文档不删除，全部保留在归档目录
- 新需求、缺陷修复、上线变更只更新新文档体系
- 如发现历史文档与当前实现冲突，以新文档和源码为准

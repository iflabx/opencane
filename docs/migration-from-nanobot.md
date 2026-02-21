# 从 nanobot 到 OpenCane 的文档迁移说明

## 本次调整内容

1. 根目录原有 nanobot 文档全部归档到 `local-docs/nanobot-legacy/`
2. 重建 OpenCane 文档体系，统一入口为根目录 `README.md` 和 `docs/README.md`
3. 文档结构从“历史演进 + 分散专题”调整为“产品化结构 + API/运维可执行手册”

## 命名与兼容

- 项目名称：OpenCane
- 代码包名：`opencane`
- CLI 命令：`opencane`（兼容 `nanobot` 别名）
- 配置目录：默认 `~/.opencane`（兼容读取 `~/.nanobot`）

## 迁移完成状态（2026-02-21）

已完成：

- 源码包目录由 `nanobot/` 迁移到 `opencane/`
- 构建与入口脚本迁移到 `opencane`（保留 CLI 别名 `nanobot`）
- 文档、脚本、测试用例中的主命令统一为 `opencane`

兼容保留：

- `nanobot` CLI 别名
- 读取历史数据目录 `~/.nanobot`
- skill frontmatter 兼容 legacy `nanobot` metadata key

不再兼容：

- `python -m nanobot`
- `from nanobot...` 导入路径

这意味着：

- 文档中的项目术语统一为 OpenCane
- 建议执行命令使用 `opencane ...`

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

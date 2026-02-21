# OpenCane Documentation

## 当前状态（2026-02-21）

- 代码包名已完成迁移：`opencane`
- CLI 主命令：`opencane`（兼容 `nanobot` 别名）
- 默认数据目录：`~/.opencane`（兼容读取 `~/.nanobot`）
- 历史文档已归档到本地目录：`../local-docs/nanobot-legacy/`

## 阅读顺序

1. `overview.md`：先理解项目边界与目标
2. `quickstart.md`：先跑通本地最小闭环
3. `architecture.md`：理解核心模块与职责
4. `data-flow.md`：理解关键链路的数据路径
5. `hardware-runtime.md`：做设备接入和联调
6. `hardware-multi-modem-adapter.md`：多蜂窝模组适配方案与用法
7. `hardware-firmware-contract.md`：固件对接契约（topic/事件/命令）
8. `api/*.md`：对接控制面、lifelog、数字任务
9. `deployment-config.md` + `operations-runbook.md`：部署与运维
10. `security.md`：上线前安全检查

## 文档目录

- 总览: `overview.md`
- 快速开始: `quickstart.md`
- 架构设计: `architecture.md`
- 数据流: `data-flow.md`
- 硬件运行时: `hardware-runtime.md`
- 多模组适配: `hardware-multi-modem-adapter.md`
- 固件对接契约: `hardware-firmware-contract.md`
- 控制 API: `api/control.md`
- Lifelog API: `api/lifelog.md`
- Digital Task API: `api/digital-task.md`
- 部署与配置: `deployment-config.md`
- 运维手册: `operations-runbook.md`
- 安全基线: `security.md`
- 路线图: `roadmap.md`
- 迁移说明: `migration-from-nanobot.md`

## 历史文档归档

- 旧版 nanobot 文档: `../local-docs/nanobot-legacy/`

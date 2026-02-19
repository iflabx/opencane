# OpenCane

OpenCane 是一个面向智能盲杖场景的 AI 后端工程，目标是把设备接入、语音交互、视觉理解、长期记忆、数字任务和安全治理整合为一套可部署的运行时。

> 当前代码包名和 CLI 命令仍保持兼容：`nanobot`。
> 项目品牌与文档已切换为 OpenCane。

## 项目定位

- 面向硬件侧：支持 `mock / websocket / ec600` 适配器接入
- 面向服务侧：统一控制 API、可观测性、任务状态持久化
- 面向业务侧：语音链路、Lifelog 图像记忆、数字任务执行与回推

## 快速开始

```bash
git clone https://github.com/iflabx/opencane.git
cd opencane
pip install -e .
```

首次初始化：

```bash
nanobot onboard
```

应用配置模板（建议先用 staging 模板）：

```bash
nanobot config profile apply --profile CONFIG_PROFILE_STAGING.json
nanobot config check --strict
```

启动硬件运行时（示例）：

```bash
nanobot hardware serve --adapter mock --logs
```

## 文档导航

- 总览: `docs/overview.md`
- 快速开始: `docs/quickstart.md`
- 架构设计: `docs/architecture.md`
- 数据流: `docs/data-flow.md`
- 硬件运行时: `docs/hardware-runtime.md`
- API 文档:
  - `docs/api/control.md`
  - `docs/api/lifelog.md`
  - `docs/api/digital-task.md`
- 部署与配置: `docs/deployment-config.md`
- 运维手册: `docs/operations-runbook.md`
- 安全基线: `docs/security.md`
- 路线图: `docs/roadmap.md`
- 迁移说明: `docs/migration-from-nanobot.md`

## 历史文档

旧版 nanobot 文档已归档到：

- `local-docs/nanobot-legacy/`

归档说明见：`local-docs/nanobot-legacy/README.md`

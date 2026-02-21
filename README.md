# OpenCane

OpenCane 是一个面向智能盲杖场景的 AI 后端运行时，聚焦“设备接入 -> 实时对话 -> 图像记忆 -> 数字任务 -> 安全与观测”的完整闭环。

> CLI 主命令为 `opencane`，并兼容 `nanobot` 别名  
> 项目品牌与产品文档已切换为 OpenCane

## 核心功能

- 多硬件接入：支持 `mock / websocket / ec600 / generic_mqtt` 适配器统一接入
- 多模组适配：`generic_mqtt` 内置 `ec600mcnle_v1 / a7670c_v1 / sim7600g_h_v1 / ec800m_v1 / ml307r_dl_v1`
- 实时语音链路：支持音频分段、VAD、转写、播报与打断处理
- 视觉 Lifelog：图像异步入库、语义检索、时间线检索与安全标注
- 数字任务执行：任务创建、状态查询、取消、离线回推与重试
- 控制面 API：设备注册绑定、设备指令下发、运行状态查询

## 技术特性

- 分层架构：`adapter / runtime / agent / api / storage / safety`
- 工具执行策略：优先 MCP 工具，失败自动回退 `web_search / web_fetch / exec`
- 任务状态机：`pending -> running -> success/failed/timeout/canceled`
- 数据存储：SQLite 持久化（lifelog / task / observability）
- 向量检索：支持 `chroma` 与 `qdrant` 后端
- 提供商适配：基于 LiteLLM 统一接入 `OpenAI / Anthropic / Gemini / DashScope` 等模型
- 运维可观测：运行时指标 + 历史观测数据，支持问题复盘
- 配置治理：内置 `dev/staging/prod` 模板与 `config check --strict`

## 快速开始

```bash
git clone https://github.com/iflabx/opencane.git
cd opencane
pip install -e .
```

首次初始化：

```bash
opencane onboard
```

应用配置模板（建议先用 staging 模板）：

```bash
opencane config profile apply --profile CONFIG_PROFILE_STAGING.json
opencane config check --strict
```

启动硬件运行时（示例）：

```bash
opencane hardware serve --adapter mock --logs
```

## 文档导航

- 总览：`docs/overview.md`
- 快速开始：`docs/quickstart.md`
- 架构设计：`docs/architecture.md`
- 数据流：`docs/data-flow.md`
- 硬件运行时：`docs/hardware-runtime.md`
- 控制 API：`docs/api/control.md`
- Lifelog API：`docs/api/lifelog.md`
- Digital Task API：`docs/api/digital-task.md`
- 部署与配置：`docs/deployment-config.md`
- 运维手册：`docs/operations-runbook.md`
- 安全基线：`docs/security.md`
- 路线图：`docs/roadmap.md`
- 迁移说明：`docs/migration-from-nanobot.md`

## 兼容边界

- Python 包与导入路径：使用 `opencane`（不再支持 `from nanobot...`）
- CLI：主命令 `opencane`，兼容 `nanobot` 别名
- 数据目录：默认 `~/.opencane`，兼容读取历史 `~/.nanobot`

## 致谢

本项目基于 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 进行持续开发与场景化演进。  
感谢 HKUDS 团队开源 nanobot，为 OpenCane 的落地提供了坚实基础。

## 历史文档

旧版 nanobot 历史文档已归档到：`local-docs/nanobot-legacy/`  
归档说明见：`local-docs/nanobot-legacy/README.md`

# OpenCane 项目总览

## 1. 项目是什么

OpenCane 是“AI Agent 平台能力 + 智能盲杖后端能力”的统一工程，服务目标是实现从设备事件到安全反馈的闭环。

核心闭环：

1. 设备上报（语音/图像/控制事件）
2. 运行时编排（ASR/VLM/Agent/任务）
3. 安全与交互策略
4. 下行反馈（文本/音频/设备控制）
5. 结构化留痕（Lifelog/任务/观测）

## 2. 能力边界

当前项目重点覆盖：

- 多适配器硬件接入（`mock/websocket/ec600/generic_mqtt`）
- 多蜂窝模组 profile（`ec600mcnle_v1/a7670c_v1/sim7600g_h_v1/ec800m_v1/ml307r_dl_v1`）
- 语音链路（VAD、转写、打断、播报）
- 图像 lifelog 入库、检索与安全标注
- 异步数字任务执行与状态回推
- 控制 API、设备操作管理、运行时观测

不在当前版本核心范围：

- 前端 App 交互界面
- OTA 固件发布平台
- 多租户控制平面 SaaS

## 3. 运行接口与兼容边界

项目品牌已切换为 OpenCane，但以下运行接口仍保持兼容：

- Python 包/导入：`opencane`
- CLI：`opencane ...`（兼容 `nanobot` 别名）
- 默认配置路径：`~/.opencane/config.json`（兼容读取 `~/.nanobot/config.json`）

不在兼容范围内：

- `python -m nanobot`
- `from nanobot...` 导入路径

## 4. 文档使用方式

- 先读：`quickstart.md`
- 联调时读：`hardware-runtime.md` + `api/control.md`
- 排障时读：`operations-runbook.md`
- 上线前读：`security.md`

## 5. 当前验证基线（2026-02-21）

在当前仓库状态下，已通过以下基线验证：

- `ruff check`
- `pytest -q`（全量用例）
- `scripts/run_control_api_smoke_ci.sh`
- `scripts/replay_contract_smoke.sh`（mock runtime）

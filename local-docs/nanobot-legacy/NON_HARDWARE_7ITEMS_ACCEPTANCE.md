# 非硬件 7 项收口验收清单（2026-02-18）

## 1. 说明

本清单用于确认“多模态盲杖后端”在**不依赖实机联调**前提下的 7 项开发收口状态。  
结论：7/7 已完成；后续追加的 P0/P1 残余 8 项也已完成，剩余仅硬件联调项。

## 2. 收口项验收

| ID | 项目 | 状态 | 代码证据 | 测试证据 |
|---|---|---|---|---|
| NH-01 | STT 多提供方回退（Groq -> OpenAI -> OpenAI-compatible） | 已完成 | `nanobot/providers/transcription.py`, `nanobot/cli/commands.py` | `tests/test_transcription_provider.py`, `tests/test_hardware_startup_strict.py` |
| NH-02 | `server_audio` 路径与 TTS 提供方（OpenAI/custom + tone fallback） | 已完成 | `nanobot/providers/tts.py`, `nanobot/hardware/runtime/connection.py`, `nanobot/cli/commands.py` | `tests/test_tts_provider.py`, `tests/test_hardware_runtime.py` |
| NH-03 | 严格启动（`--strict-startup`）与依赖降级/失败策略 | 已完成 | `nanobot/cli/commands.py` | `tests/test_hardware_startup_strict.py` |
| NH-04 | Observability 历史持久化（独立 sqlite，且无 lifelog 也可恢复） | 已完成 | `nanobot/storage/sqlite_observability.py`, `nanobot/api/hardware_server.py` | `tests/test_hardware_control_digital_task_api.py` |
| NH-05 | SQLite schema version + migration（lifelog/tasks） | 已完成 | `nanobot/storage/sqlite_lifelog.py`, `nanobot/storage/sqlite_tasks.py` | `tests/test_storage_migrations.py` |
| NH-06 | 配置模型与模板补齐（strict/observability/tts chunk） | 已完成 | `nanobot/config/schema.py`, `CONFIG_PROFILE_DEV.json`, `CONFIG_PROFILE_STAGING.json`, `CONFIG_PROFILE_PROD.json` | `tests/test_hardware_config_profiles.py`, `tests/test_config_profile_templates.py` |
| NH-07 | CI 冻结门禁与文档口径对齐 | 已完成 | `.github/workflows/ci.yml`, `README.md`, `SRE_RUNBOOK.md`, `HARDWARE_OBSERVABILITY.md`, `BLIND_CANE_BACKEND_DESIGN.md` | `python3 -m ruff check .` + `python3 -m pytest -x` 全量通过 |

## 3. 本轮修复补充（2026-02-18）

1. 修复 observability history 回退逻辑覆盖问题，避免 sqlite 结果被内存回退覆盖：`nanobot/api/hardware_server.py`  
2. 清理文档中过时引用（`nanobot/channels/blindcane.py`、`nanobot/api/server.py`），统一为当前 `nanobot hardware serve` + `hardware_server` 架构：`BLIND_CANE_BACKEND_DESIGN.md`

## 4. 回归结果

1. `python3 -m ruff check .`：通过  
2. `python3 -m pytest -x`：通过（`214 passed, 1 warning`）

## 5. 剩余项（仅硬件联调）

硬件相关遗留已独立维护，不在本清单范围：

1. `HARDWARE_PENDING_ISSUES.md`
2. `HARDWARE_JOINT_DEBUG_DEFERRED.md`

当前建议以这三项作为恢复触发：

1. MQTT/Broker 联调信息补齐  
2. EC600 协议样例/抓包补齐  
3. 最小设备联调路径可执行

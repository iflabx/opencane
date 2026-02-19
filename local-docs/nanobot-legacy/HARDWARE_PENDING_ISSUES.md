# 硬件相关遗留问题清单（P1收口）

## 1. 文档目的

本清单用于统一记录当前 `nanobot` 在“多模态盲杖后端 P1 阶段”中的硬件相关遗留问题。
由于当前尚未进入实机调试，本清单将问题分为：

1. 无硬件可先完成（代码级修复/增强）
2. 需硬件联调才能闭环（协议对齐/性能/稳定性）

## 2. 当前范围

- 目标阶段：P1（接口与骨架）
- 已具备：统一协议、运行时核心、WS/EC600 适配器、基础控制 API、基础视觉入口
- 未进入：实机（EC600 + 盲杖终端）联调

## 3. 硬件遗留问题总览（按优先级）

| ID | 优先级 | 问题 | 当前状态 | 代码位置 |
|---|---|---|---|---|
| HW-01 | P0 | EC600 控制消息 `session_id` 连续性风险 | 已修复（2026-02-17） | `nanobot/hardware/adapter/ec600_adapter.py` |
| HW-02 | P0 | 重复包去重后未回 ACK，设备可能反复重传 | 已修复（2026-02-17） | `nanobot/hardware/runtime/connection.py` |
| HW-03 | P0 | 纯音频场景未接入真实转写函数，语音链路不完整 | 代码已修复，待联调验证（2026-02-17） | `nanobot/hardware/runtime/audio_pipeline.py` / `nanobot/hardware/runtime/connection.py` / `nanobot/cli/commands.py` |
| HW-04 | P1 | `server_audio` 后端链路已具备，但 EC600 下行二进制音频仍未完成实机闭环 | 后端已实现，待联调验证（2026-02-18） | `nanobot/hardware/runtime/connection.py` / `nanobot/hardware/adapter/ec600_adapter.py` / `nanobot/config/schema.py` |
| HW-05 | P1 | 控制 API 未鉴权，存在事件注入风险 | 代码已修复（2026-02-17） | `nanobot/api/hardware_server.py` / `nanobot/cli/commands.py` |
| HW-06 | P1 | 弱网重连恢复（resume/补发窗口）未实现 | 代码已修复，待联调验证（2026-02-17） | `nanobot/hardware/adapter/ec600_adapter.py` / `nanobot/config/schema.py` |
| HW-10 | P1 | 下行控制命令 `seq` 大量为 0，导致重放窗口有效性不足 | 代码已修复（2026-02-17） | `nanobot/hardware/runtime/connection.py` / `nanobot/hardware/runtime/session_manager.py` |
| HW-11 | P1 | 控制 API `future.result(timeout=...)` 异常未结构化返回 | 代码已修复（2026-02-17） | `nanobot/api/hardware_server.py` |
| HW-12 | P1 | 协议冻结前缺少可执行校验脚本 | 代码已修复（2026-02-17） | `nanobot/hardware/validate_protocol.py` / `EC600_PROTOCOL_MAPPING_TEMPLATE.md` |
| HW-07 | P1 | MQTT topic 与 payload 字段尚未与 EC600 实际固件协议冻结 | 待联调 | `nanobot/hardware/adapter/ec600_adapter.py` + 设备固件协议 |
| HW-08 | P1 | 音频包头 v0.1 与实机帧结构一致性未验证 | 待联调 | `nanobot/hardware/adapter/ec600_adapter.py` |
| HW-09 | P2 | 心跳/超时阈值未按蜂窝网络场景压测调优 | 预设已落地，待联调定版（2026-02-17） | `nanobot/config/schema.py` / `nanobot/hardware/runtime/connection.py` / `nanobot/cli/commands.py` |

## 4. 分问题说明与处理策略

### HW-01 会话连续性风险（P0）

- 现象：控制消息解析时，若终端未显式携带 `session_id`，当前实现可能创建新会话，导致同一设备会话漂移。
- 无硬件阶段可做：
  1. 控制消息解析补 `default_session_id`（优先复用 `_session_by_device`）
  2. 增加对应单测（无 `session_id` 时应复用旧会话）
- 联调阶段验证：
  1. 设备断线重连后会话是否连续
  2. 连续控制帧是否保持同一 `session_id`
- 已完成：
  1. 控制消息解析增加 `default_session_id` 复用策略（优先复用设备已有会话）
  2. 无会话时改为稳定默认会话 `device_id-default`（避免随机新会话）
  3. 增加单测覆盖（无 session_id 场景）

### HW-02 去重后未 ACK（P0）

- 现象：重复 `seq` 被直接丢弃，未显式 ACK，弱网时设备可能持续重传并放大拥塞。
- 无硬件阶段可做：
  1. 在去重分支回 ACK（对可 ACK 事件）
  2. 增加重复包回 ACK 单测
- 联调阶段验证：
  1. 人工注入重复包，确认设备停止重传
  2. 弱网模拟下重复率与 RTT 变化
- 已完成：
  1. 重复包分支新增 ACK 策略（`heartbeat/listen_start/listen_stop/telemetry`）
  2. 重复 `hello` 分支改为重发 `hello_ack`
  3. 增加回归测试覆盖重复 `heartbeat` ACK 场景

### HW-03 纯音频未打通转写（P0）

- 现象：`AudioPipeline` 的 `transcribe_fn` 默认未注入，纯音频输入下可能无可用 transcript。
- 无硬件阶段可做：
  1. 在 `hardware serve` 初始化时注入 `TranscriptionProvider` 回调
  2. 明确错误与降级策略（转写失败时返回固定提示）
- 联调阶段验证：
  1. 真机麦克风音频可稳定产出 `stt_final`
  2. 连续说话、打断场景下无明显串话
- 已完成：
  1. `hardware serve` 初始化接入 `GroqTranscriptionProvider` 转写回调
  2. `AudioPipeline` 在纯音频路径可调用真实转写接口
  3. 新增 `transcribe_bytes` 能力与对应单测

### HW-04 下行音频通道闭环不足（P1）

- 现象：运行时当前发送 `tts_chunk` 以文本为主；EC600 二进制音频下行逻辑仅在 payload 含 `audio_b64` 时触发。
- 无硬件阶段可做：
  1. 明确 P1 策略：文本 TTS 在设备侧合成 或 服务端 TTS 音频下发（二选一）
  2. 若选服务端音频下发，补一个最小 TTS 编码适配器
- 联调阶段验证：
  1. 设备端实际播报链路稳定
  2. 中断/恢复播报时序正确
- 已完成：
  1. 后端已支持 `hardware.tts_mode=server_audio`（OpenAI/custom 优先，tone fallback）
  2. 运行时可下发 `tts_chunk.audio_b64`，并配置化 `hardware.tts_audio_chunk_bytes`
  3. 运行日志增加 `tts_mode` 输出，便于联调确认链路模式
- 待联调：
  1. EC600 设备侧二进制音频接收/播报完整闭环验证

### HW-05 控制 API 鉴权缺失（P1）

- 现象：控制 API 可直接注入事件/abort，存在被误用风险。
- 无硬件阶段可做：
  1. 增加 token 鉴权（建议复用 `hardware.auth`）
  2. 默认仅监听 `127.0.0.1`，并在 README 标注风险
- 联调阶段验证：
  1. 未授权请求返回 401/403
  2. 已授权请求不影响现有调试能力
- 已完成：
  1. 控制 API 新增 token 鉴权（支持 `Authorization: Bearer` 与 `X-Auth-Token`）
  2. `hardware serve` 已透传 `hardware.auth` 配置到控制服务
  3. 新增鉴权判断单测

### HW-06 弱网恢复能力不足（P1）

- 现象：断线期间命令可能丢弃，未做 resume token/补发窗口。
- 无硬件阶段可做：
  1. 先做轻量缓存窗口（仅控制命令）
  2. 设计 resume 字段并保持向后兼容
- 联调阶段验证：
  1. 断网 10-30 秒后恢复，关键控制命令可恢复到一致状态
  2. 不补发历史音频，仅恢复状态型命令
- 已完成：
  1. 增加控制命令离线缓冲（`offline_control_buffer`）
  2. 增加控制命令重放窗口（`control_replay_window`）并支持 `last_recv_seq` 回放
  3. 设备 `hello` 后自动触发按设备补发/回放（仅控制命令，不回放音频）
  4. 补充无 broker 单测覆盖缓冲与回放行为
  5. 修复 `hello` 时 replay/flush 顺序，避免 pending 指令在同次恢复中重复下发
  6. 当 `replay_enabled=false` 时仍保留 pending flush，避免关闭重放后丢补发能力

### HW-10 下行命令序号体系不足（P1）

- 现象：`stt_final/tts_*` 等命令多为默认 `seq=0`，`last_recv_seq` 重放过滤效果受限。
- 无硬件阶段可做：
  1. 引入会话级 outbound 序号分配器
  2. 统一由 runtime 生成下行命令序号（含 ACK/HELLO_ACK/STT/TTS）
  3. 增加序号递增单测
- 联调阶段验证：
  1. 设备端 `last_recv_seq` 与后端下行序号一致前进
  2. 断线恢复后仅重放未确认控制命令
- 已完成：
  1. `DeviceSessionManager` 新增 `next_outbound_seq`
  2. runtime 下行命令统一走会话级递增 `seq`
  3. 新增命令序号递增回归测试

### HW-11 控制 API 超时/异常兜底不足（P1）

- 现象：控制 API 中多个 `future.result(timeout=...)` 缺少统一异常处理，可能直接抛异常。
- 无硬件阶段可做：
  1. 统一 future 结果解析函数
  2. 超时返回 `504`，运行时异常返回 `500`
  3. 增加单测覆盖
- 联调阶段验证：
  1. 压测/故障注入时控制 API 返回结构稳定
  2. 不影响已有调试能力（abort/event/vision）
- 已完成：
  1. 新增 `_resolve_future_result` 统一处理
  2. 接口在超时/异常下返回结构化错误 JSON
  3. 增加超时/异常单测

### HW-12 协议冻结前自动校验能力缺失（P1）

- 现象：协议模板需要人工检查，联调前容易漏填字段或遗漏章节。
- 无硬件阶段可做：
  1. 增加可执行校验脚本
  2. 提供 draft/freeze 两种校验级别
  3. 将命令写入模板文档
- 联调阶段验证：
  1. freeze 前 CI 或本地脚本能阻断未冻结版本
  2. 协议文档字段完整且无 `Draft/待填写`
- 已完成：
  1. 新增 `python3 -m nanobot.hardware.validate_protocol`
  2. 支持 `--stage draft|freeze`
  3. 模板文档新增脚本使用说明与约束

### HW-07 Topic/字段冻结（P1，联调必需）

- 现象：当前 topic 与 payload 是后端临时协议，尚未与硬件固件最终冻结。
- 无硬件阶段可做：
  1. 产出协议对照表（后端字段 -> 固件字段）
  2. 预留映射层，避免核心 runtime 被私有字段污染
- 已完成（无硬件阶段）：
  1. 已新增协议对照模板：`EC600_PROTOCOL_MAPPING_TEMPLATE.md`
- 联调阶段验证：
  1. hello/heartbeat/audio/control 全链路一致
  2. 错误码与异常帧处理一致

### HW-08 音频包头一致性（P1，联调必需）

- 现象：当前按 16 字节头解析，含 `magic/version/seq/ts/len`；未与实机抓包核验。
- 无硬件阶段可做：
  1. 保留 parser 可配置项（magic/version/endianness）
  2. 增加畸形包测试
- 联调阶段验证：
  1. 抓包确认字段偏移与字节序
  2. 长包/短包/粘包场景稳定

### HW-09 心跳与超时调优（P2）

- 现象：当前阈值是通用默认值，蜂窝网络下可能需要更保守设置。
- 无硬件阶段可做：
  1. 将阈值全部配置化并加注释
  2. 增加建议默认值（蜂窝 profile）
- 已完成（无硬件阶段）：
  1. 增加 `hardware.network_profile=cellular` 与 `apply_profile_defaults`
  2. 启动时应用蜂窝保守参数预设（心跳/keepalive/reconnect）
  3. 运行日志输出 profile 与关键网络参数
- 联调阶段验证：
  1. 实网环境下误判离线率
  2. 保活开销与稳定性平衡

## 5. 建议执行顺序（当前剩余）

1. 先完成 HW-07 协议字段与 topic 冻结（产出 `EC600_PROTOCOL_MAPPING_V1.md`）
2. 在同一轮联调中完成 HW-08 包头抓包核验并修正解析细节
3. 基于实网数据完成 HW-09 参数压测与默认值定版
4. 对 HW-03/HW-06/HW-10/HW-11 做实机回归验收并更新状态为 Fully Verified

## 6. 联调前置条件（硬件可用后）

1. 提供 EC600 侧协议说明或抓包样例（control/audio 上下行）
2. 提供设备端 `session_id/seq` 生成规则
3. 提供设备端 TTS 方案（本地合成或接收音频流）
4. 提供最小联调脚本（发 hello/listen/audio/listen_stop）

## 7. 更新记录

- 2026-02-17：初始化本遗留清单（基于当前 P1 代码状态）
- 2026-02-17：HW-01 修复完成（会话连续性），并补充对应单测
- 2026-02-17：HW-02 修复完成（重复包 ACK），并补充对应单测
- 2026-02-17：HW-03 代码修复完成（纯音频转写接入），待实机联调验证
- 2026-02-17：HW-04 策略冻结完成（P1 使用 device_text；server_audio 待后续）
- 2026-02-17：HW-05 代码修复完成（控制 API 鉴权），并补充对应单测
- 2026-02-17：HW-06 代码修复完成（弱网恢复最小实现），待实机联调验证
- 2026-02-17：HW-10 代码修复完成（下行命令统一递增 seq），并补充对应单测
- 2026-02-17：HW-11 代码修复完成（控制 API 超时/异常结构化返回），并补充对应单测
- 2026-02-17：HW-12 代码修复完成（协议映射可执行校验脚本 + 模板说明）
- 2026-02-17：HW-09 增加蜂窝网络参数预设（非最终值），待实网联调定版

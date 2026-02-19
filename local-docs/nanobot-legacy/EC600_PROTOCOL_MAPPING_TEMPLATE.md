# EC600 协议对照表模板（HW-07）

## 1. 目标

用于冻结“后端统一协议（Canonical）”与“EC600 固件实际协议”之间的映射关系。

使用方式：
1. 后端先填写 `Canonical` 列（已预填）。
2. 联调时补齐 `固件字段/样例` 列。
3. 对齐完成后将状态改为 `Frozen`，并记录版本号。

---

## 2. 协议版本与状态

- 后端协议版本：`v0.1`
- 设备协议版本：`待填写`
- 当前状态：`Draft`
- 冻结时间：`待填写`
- 负责人（后端/固件）：`待填写`

---

## 3. 主题（MQTT Topic）映射

| 方向 | Canonical Topic | 固件 Topic | QoS | 状态 | 备注 |
|---|---|---|---|---|---|
| Device -> Server | `device/{device_id}/up/control` | 待填写 | 1 | Draft | 控制/状态事件 |
| Device -> Server | `device/{device_id}/up/audio` | 待填写 | 0 | Draft | 二进制音频帧 |
| Server -> Device | `device/{device_id}/down/control` | 待填写 | 1 | Draft | 控制指令/文本TTS |
| Server -> Device | `device/{device_id}/down/audio` | 待填写 | 0 | Draft | 二进制下行音频（后续） |
| Server -> Broker | `nanobot/hardware/heartbeat` | 待填写 | 0 | Draft | 后端健康上报 |

---

## 4. 统一消息信封映射（Control JSON）

| Canonical 字段 | 类型 | 必填 | Canonical 说明 | 固件字段名 | 固件样例 | 状态 |
|---|---|---|---|---|---|---|
| `version` | string | 否 | 默认 `0.1` | 待填写 | 待填写 | Draft |
| `msg_id` | string | 否 | UUID | 待填写 | 待填写 | Draft |
| `device_id` | string | 是 | 设备唯一ID | 待填写 | 待填写 | Draft |
| `session_id` | string | 建议 | 会话ID；缺省将复用/自动生成 | 待填写 | 待填写 | Draft |
| `seq` | int | 建议 | 单会话递增序号 | 待填写 | 待填写 | Draft |
| `ts` | int(ms) | 建议 | 事件时间戳 | 待填写 | 待填写 | Draft |
| `type` | string | 是 | 事件/指令类型 | 待填写 | 待填写 | Draft |
| `payload` | object | 否 | 类型相关载荷 | 待填写 | 待填写 | Draft |

---

## 5. 上行事件映射（Device -> Server）

| Canonical `type` | 最小 Canonical payload | 固件事件名 | 固件payload样例 | 状态 | 备注 |
|---|---|---|---|---|---|
| `hello` | `capabilities`(可选) | 待填写 | 待填写 | Draft | 用于会话建立与能力协商 |
| `heartbeat` | 可空 | 待填写 | 待填写 | Draft | 用于保活 |
| `listen_start` | 可空 | 待填写 | 待填写 | Draft | 开始收音 |
| `audio_chunk` | `audio_b64` 或二进制音频帧 | 待填写 | 待填写 | Draft | 二进制走 `up/audio` |
| `listen_stop` | `text/transcript`(可选) | 待填写 | 待填写 | Draft | 结束收音 |
| `abort` | `reason`(可选) | 待填写 | 待填写 | Draft | 打断当前播报/任务 |
| `image_ready` | `image_base64` + `question`(可选) | 待填写 | 待填写 | Draft | 图片分析触发 |
| `telemetry` | 任意对象 | 待填写 | 待填写 | Draft | 传感数据 |
| `error` | `error` | 待填写 | 待填写 | Draft | 设备上报错误 |

---

## 6. 下行指令映射（Server -> Device）

| Canonical `type` | 最小 Canonical payload | 固件指令名 | 固件payload样例 | 状态 | 备注 |
|---|---|---|---|---|---|
| `hello_ack` | `runtime/protocol/session_id` | 待填写 | 待填写 | Draft | hello 回应 |
| `ack` | `ack_seq` | 待填写 | 待填写 | Draft | 事件确认 |
| `stt_final` | `text` | 待填写 | 待填写 | Draft | 语音识别最终结果 |
| `tts_start` | `text`(预览) | 待填写 | 待填写 | Draft | 播报开始 |
| `tts_chunk` | `text` 或 `audio_b64` | 待填写 | 待填写 | Draft | P1 当前用 `text` |
| `tts_stop` | `aborted` | 待填写 | 待填写 | Draft | 播报结束 |
| `task_update` | `task_id/status/message/task` | 待填写 | 待填写 | Draft | 数字任务状态推送（pending/running/success/failed/timeout/canceled） |
| `close` | `reason` | 待填写 | 待填写 | Draft | 主动关闭会话 |

---

## 7. 二进制音频包头映射（16 bytes）

| 偏移 | 长度 | Canonical 定义 | 固件字段名 | 字节序 | 状态 | 备注 |
|---|---|---|---|---|---|---|
| 0 | 1 | `magic` | 待填写 | - | Draft | 默认 `0xA1` |
| 1 | 1 | `version` | 待填写 | - | Draft | 默认 `1` |
| 2 | 1 | `type`(预留) | 待填写 | - | Draft | 当前未用 |
| 3 | 1 | `flags`(预留) | 待填写 | - | Draft | 当前未用 |
| 4 | 4 | `seq` | 待填写 | Big Endian | Draft | `uint32` |
| 8 | 4 | `timestamp_ms` | 待填写 | Big Endian | Draft | `uint32` |
| 12 | 4 | `payload_len` | 待填写 | Big Endian | Draft | `uint32` |
| 16 | N | `payload` | 待填写 | - | Draft | 音频字节（opus/pcm） |

---

## 8. 重连恢复字段映射（HW-06 联动）

在 `hello.payload` 中建议对齐以下字段：

| Canonical 字段 | 说明 | 固件字段名 | 固件样例 | 状态 |
|---|---|---|---|---|
| `last_recv_seq` | 设备已收到的最后下行控制序号 | 待填写 | 待填写 | Draft |
| `resume_token` | 会话恢复标识（可选） | 待填写 | 待填写 | Draft |

备注：后端当前已支持根据 `last_recv_seq` 做控制命令窗口重放（不重放音频）。

---

## 9. 错误码与异常语义映射

| 场景 | Canonical 语义 | 固件错误码 | 触发条件 | 处理策略 | 状态 |
|---|---|---|---|---|---|
| 控制JSON非法 | `error: invalid control payload` | 待填写 | JSON解析失败 | 记录并告警 | Draft |
| 音频包非法 | `error: invalid audio packet` | 待填写 | magic/len异常 | 丢弃并告警 | Draft |
| 鉴权失败 | `unauthorized` | 待填写 | token错误 | 拒绝请求 | Draft |

---

## 10. 联调抓包记录（每轮补充）

### 10.1 第一次联调
- 日期：`待填写`
- 固件版本：`待填写`
- 结论：`待填写`
- 偏差项：
  1. 待填写
  2. 待填写

### 10.2 第二次联调
- 日期：`待填写`
- 固件版本：`待填写`
- 结论：`待填写`
- 偏差项：
  1. 待填写

---

## 11. 冻结清单（Freeze Checklist）

1. Topic 与 QoS 已一致
2. `hello/heartbeat/listen/audio` 事件字段已一致
3. `ack/tts/stt/task_update/close` 指令字段已一致
4. 音频包头偏移、字节序、长度规则已一致
5. 重连恢复字段已一致
6. 错误码表已一致
7. 回归脚本已通过

冻结签字：
- 后端：`待填写`
- 固件：`待填写`
- 日期：`待填写`

---

## 12. 校验脚本（本地可执行）

在仓库根目录执行：

```bash
python3 -m nanobot.hardware.validate_protocol --stage draft
python3 -m nanobot.hardware.validate_protocol --stage freeze
```

- `draft`：校验结构完整性，允许存在 `Draft/待填写`
- `freeze`：要求状态为 `Frozen` 且不允许存在 `Draft/待填写`

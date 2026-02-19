# 通用边缘硬件适配层与临时协议 v0（面向多模态盲杖后端）

## 1. 目标

在没有硬件最终接口文档前，先完成后端核心能力开发，并保证后续对接不同模组时只改南向适配层。

设计原则：
- 内核稳定：语音、记忆、多模态、工具编排不依赖硬件协议细节
- 协议可替换：支持 MQTT / WebSocket / HTTP 等不同接入形态
- 低耦合：设备差异封装在 Adapter 插件
- 弱网优先：对蜂窝网络断连、抖动、丢包有恢复机制

---

## 2. 总体架构

```text
Device (EC600 / ESP32 / Other)
        |
        | Raw protocol (MQTT/WS/HTTP + binary/json)
        v
[Southbound Adapter Plugin]
        |
        | Canonical Event / Canonical Command
        v
[Device Runtime Core]
  - Session/Connection State
  - Audio Pipeline (VAD/ASR/TTS)
  - Multimodal Router
  - Memory Orchestrator
  - Tool Orchestrator
        |
        +--> Control Plane Client (config/twin/ota/audit)
        +--> LLM/VLM Providers
```

关键点：
- 任何具体模组仅实现 Adapter 映射，不进入 Runtime Core。
- Runtime Core 只处理统一事件，不处理 AT 指令或私有包格式。

---

## 3. Canonical 统一语义模型

## 3.1 统一消息信封

```json
{
  "version": "0.1",
  "msg_id": "uuid",
  "device_id": "string",
  "session_id": "string",
  "seq": 123,
  "ts": 1730000000000,
  "type": "event_or_command_type",
  "payload": {}
}
```

字段定义：
- `version`: 协议版本
- `msg_id`: 幂等与追踪 ID
- `device_id`: 设备唯一标识
- `session_id`: 会话 ID（无则由服务端分配）
- `seq`: 单会话递增序列号
- `ts`: 设备侧或服务端时间戳（毫秒）
- `type`: 消息语义类型
- `payload`: 业务载荷

## 3.2 统一事件类型（Device -> Server）

- `hello`
- `heartbeat`
- `listen_start`
- `audio_chunk`
- `listen_stop`
- `abort`
- `image_ready`
- `telemetry`
- `tool_result`
- `error`

## 3.3 统一命令类型（Server -> Device）

- `hello_ack`
- `tts_start`
- `tts_chunk`
- `tts_stop`
- `stt_partial`
- `stt_final`
- `task_update`
- `tool_call`
- `set_config`
- `ota_plan`
- `close`

说明：`task_update` 用于下发数字任务状态（`pending/running/success/failed/timeout/canceled`）与摘要消息。

---

## 4. Adapter SDK 接口（建议）

以下接口用于约束所有硬件适配器（EC600、ESP32、其他边缘模组）：

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, AsyncIterator


@dataclass
class CanonicalEnvelope:
    version: str
    msg_id: str
    device_id: str
    session_id: str
    seq: int
    ts: int
    type: str
    payload: dict[str, Any]


class GatewayAdapter(Protocol):
    name: str
    transport: str  # mqtt/ws/http

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def recv_events(self) -> AsyncIterator[CanonicalEnvelope]:
        """Raw inbound -> Canonical events"""
        ...

    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        """Canonical command -> Raw outbound"""
        ...

    async def ack(self, device_id: str, session_id: str, seq: int) -> None:
        ...

    async def close_session(self, device_id: str, session_id: str, reason: str) -> None:
        ...
```

实施约束：
- Adapter 不做业务决策（不做 LLM 调用、不做记忆）。
- Adapter 只做协议转换、连接管理、重传/去重基础能力。
- Core 通过 `GatewayAdapter` 抽象与设备通信。

---

## 5. 临时协议 v0.1（可立即联调）

## 5.1 传输建议

- 控制流：MQTT JSON（QoS1）
- 音频流：MQTT binary（QoS0 + seq）
- 图片：HTTP 上传（避免大 payload 挤占 MQTT）

## 5.2 topic 建议（MQTT）

- 上行（设备 -> 服务）：
  - `device/{device_id}/up/control`
  - `device/{device_id}/up/audio`
- 下行（服务 -> 设备）：
  - `device/{device_id}/down/control`
  - `device/{device_id}/down/audio`

## 5.3 音频二进制包头（16 bytes）

建议字段：
- byte0: `magic`
- byte1: `version`
- byte2: `type` (audio/control flags)
- byte3: `flags`
- byte4-7: `seq` (uint32)
- byte8-11: `timestamp_ms` (uint32)
- byte12-15: `payload_len` (uint32)

后接 `payload`（例如 opus frame）。

## 5.4 会话状态机（最小版）

`DISCONNECTED -> CONNECTED -> AUTHED -> READY -> LISTENING -> THINKING -> SPEAKING -> READY`

异常态：
- 任意状态收到 `abort` -> `READY`
- 心跳超时 -> `DISCONNECTED`
- 认证失败 -> `CLOSE`

---

## 6. 可靠性与弱网策略（蜂窝网络重点）

## 6.1 幂等与去重

- 以 `(device_id, session_id, seq)` 作为去重键
- 重复包直接 ack，不重复入队

## 6.2 重连恢复

设备重连时上报：
- `resume_token`
- `last_recv_seq`
- `last_sent_seq`

服务端按窗口补发控制消息，不补发历史音频。

## 6.3 心跳

- 心跳周期：15-30s（蜂窝建议更短）
- 连续 N 次超时（如 3 次）判定离线

## 6.4 重试

- 控制消息指数退避重试：1s / 2s / 4s / 8s（上限可配置）
- 音频不重传（实时优先）

---

## 7. 安全建议（v0 就应具备）

- 设备身份：`device_id + client_id + token`
- token：短期有效 + 可轮换
- 设备绑定：未绑定设备只允许激活/绑定流程消息
- 最小权限：设备仅能访问自己的 topic / session

---

## 8. 能力协商（跨模组通用）

`hello.payload.capabilities` 示例：

```json
{
  "network": "cellular",
  "audio_codecs": ["opus", "pcm16"],
  "sample_rates": [16000],
  "camera": true,
  "image_max_bytes": 2097152,
  "supports_partial_stt": true,
  "supports_stream_tts": true,
  "firmware_version": "0.1.0"
}
```

服务端据此下发策略：
- 选择 codec 和采样率
- 控制 chunk 大小
- 决定是否启用流式 TTS/STT

---

## 9. EC600MCNLE 专项配置建议

由于是蜂窝模组，先用保守配置：
- 音频分片初始 `<= 512B`，联调稳定后再放大
- 心跳 20s
- 控制 QoS1，音频 QoS0
- 图片使用 HTTP 分片上传，不走 MQTT
- 强制启用重连会话恢复（`resume_token`）

---

## 10. 开发落地顺序（建议两周起步）

1. 冻结 `protocol_v0.1` 文档与错误码。
2. 实现 `MockAdapter` + 回放测试集。
3. 接入 Runtime Core（会话状态机、音频队列、打断策略）。
4. 实现 `EC600Adapter`（先控制流，再音频流）。
5. 加入 conformance tests（协议一致性、乱序、重放、断线恢复）。
6. 硬件文档到位后，仅替换 Adapter 映射，不改 Core 业务。

---

## 11. 对 nanobot 当前工程的建议改造位

- 新增目录：
  - `nanobot/hardware/adapter/`
  - `nanobot/hardware/runtime/`
  - `nanobot/hardware/protocol/`
  - `nanobot/hardware/tests/`
- 将硬件连接入口与现有 `nanobot/agent/loop.py` 解耦。
- `nanobot/agent/context.py` 保留多模态拼装能力，作为上层能力复用。

---

## 12. 结论

这套方案的核心是：  
先把“协议不确定性”封装进 Adapter，再让 Core 稳定迭代语音、记忆、多模态能力。  
这样即使后续硬件接口文档变化，主要修改点也会被限制在南向适配层。

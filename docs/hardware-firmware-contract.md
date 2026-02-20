# 硬件固件对接契约（v1）

## 1. 目的

本文档面向硬件/固件工程，定义盲杖设备与后端之间的最小接口契约。  
目标是让不同蜂窝模组共用同一套后端 Runtime，仅在适配配置（profile）层处理差异。

## 2. 传输与适配模式

- 传输协议：MQTT
- 适配器：
  - `generic_mqtt`（推荐，支持多模组 profile）
  - `ec600`（兼容旧路径）
- 音频上行格式：
  - `framed_packet`（默认，16 字节头 + 音频体）
  - `json_b64`（可选，JSON 中携带 base64 音频）

## 3. Topic 约定（默认）

- 上行控制：`device/{device_id}/up/control`
- 上行音频：`device/{device_id}/up/audio`
- 下行控制：`device/{device_id}/down/control`
- 下行音频：`device/{device_id}/down/audio`

`generic_mqtt` 下可由 `hardware.profileOverrides.mqtt.*` 覆盖。

## 4. 上行事件（设备 -> 后端）

必需事件：

1. `hello`：设备上线与能力协商  
2. `heartbeat`：保活  
3. `listen_start`：开始采集  
4. `audio_chunk`：语音分片  
5. `listen_stop`：结束采集  

可选事件：

1. `image_ready`：图像上传完成（携带 URL 或 asset_id）  
2. `telemetry`：状态/传感器数据（可为空）  
3. `tool_result`：工具执行回执（可选）  

最小字段（统一协议）：

- `device_id`、`session_id`、`seq`、`type`、`payload`

## 5. 下行命令（后端 -> 设备）

常用命令：

1. `hello_ack`
2. `tts_start`
3. `tts_chunk`
4. `tts_stop`
5. `task_update`
6. `ack`
7. `close`

说明：

- `tts_chunk` 可能是文本（控制通道）或二进制音频（音频通道，取决于配置）。
- 设备应容忍未知字段，忽略不认识的扩展键。

## 6. 音频格式契约

### 6.1 `framed_packet`（默认）

- Header 长度：16 字节
- `byte[0]`：`packet_magic`（默认 `0xA1`，可覆盖）
- `byte[4:8]`：`seq`（big-endian）
- `byte[8:12]`：`timestamp`（big-endian）
- `byte[12:16]`：payload 长度（big-endian）
- 后续字节：音频体

### 6.2 `json_b64`（可选）

JSON 示例：

```json
{
  "device_id": "dev-001",
  "session_id": "sess-001",
  "seq": 10,
  "timestamp": 1730000000,
  "audioBase64": "BASE64_AUDIO",
  "codec": "opus"
}
```

## 7. 内置模组 Profile（v1）

- `ec600mcnle_v1`
- `a7670c_v1`
- `sim7600g_h_v1`
- `ec800m_v1`
- `ml307r_dl_v1`

建议：

- 量产先锁一条主 profile（如 `ec800m_v1`），其余作为备选。
- 联调初期不要改 topic 命名，只在 profile 中调整超时与重连参数。

## 8. 联调最小流程

1. 设备发送 `hello`
2. 后端返回 `hello_ack`
3. 设备发送 `listen_start`
4. 设备连续发送 `audio_chunk`
5. 设备发送 `listen_stop`
6. 后端下发 `tts_start/tts_chunk/tts_stop`

验证接口：

- `GET /v1/runtime/status`
- `GET /v1/runtime/observability`

## 9. 故障排查

- 无法识别消息：检查上行 control topic 与 JSON 格式。
- 语音无结果：确认音频格式与 `audioUpMode` 一致。
- 会话错乱：确认 `session_id` 在单回合内保持一致。
- 经常断链：提高 keepalive 与重连窗口，优先使用蜂窝保守参数。

# 项目数据类型与数据流程分析

## 1. 目标与范围
本文梳理当前代码中实际存在的数据类型（图片、语音、文本、遥测/IMU、任务、审计、观测等）及其端到端流转路径：

- 入口：设备事件/API
- 运行时处理：Runtime/Service/Pipeline
- 持久化：SQLite/文件资产/向量索引/本地记忆文件
- 输出：设备回传与查询接口

---

## 2. 全局主链路
`设备或模拟器事件` -> `CanonicalEnvelope` 标准化 -> `DeviceRuntimeCore.handle_event` 分发 -> `Audio/Vision/Lifelog/DigitalTask` 子流程 -> `SQLite + 向量索引 + 文件资产` -> `HTTP API 查询与回放`

关键代码：

- 协议封装：`nanobot/hardware/protocol/envelope.py:50`
- 事件分发：`nanobot/hardware/runtime/connection.py:148`
- API 注入事件：`nanobot/api/hardware_server.py:819`

---

## 3. 数据类型与流程

### 3.1 协议与会话元数据
数据字段：

- `version/msg_id/device_id/session_id/seq/ts/type/payload`

流程：

1. 设备事件进入 `CanonicalEnvelope.from_dict` 标准化。
2. Runtime 依据 `type` 分支处理（hello/heartbeat/listen/audio/image/telemetry/error）。
3. 会话状态、元数据、遥测写入 `device_sessions`。

存储与查询：

- 表：`device_sessions`
- 查询接口：`/v1/runtime/status`、`/v1/lifelog/device_sessions`

关键代码：

- `nanobot/hardware/protocol/envelope.py:63`
- `nanobot/hardware/runtime/connection.py:148`
- `nanobot/storage/sqlite_lifelog.py:143`
- `nanobot/api/lifelog_service.py:800`

### 3.2 语音原始数据（音频帧）
数据字段：

- `audio_b64`（兼容 `audio`）
- 可选顺序号与 VAD 提示

流程：

1. `audio_chunk` 进入 `AudioPipeline.append_chunk`。
2. 执行乱序重排、预缓冲、VAD 过滤与拼接。
3. `listen_stop` 触发 `finalize_capture`，优先用显式 transcript，否则拼接音频走转写函数。

存储与输出：

- 原始音频本身默认不直接入库。
- 回合结果以事件形式写入 lifelog（延迟、成功率等）。

关键代码：

- `nanobot/hardware/runtime/connection.py:212`
- `nanobot/hardware/runtime/audio_pipeline.py:71`
- `nanobot/hardware/runtime/audio_pipeline.py:104`

### 3.3 语音文本数据（STT/Agent/TTS）
数据字段：

- STT：`stt_partial.text`、`stt_final.text`
- 对话：`transcript`、`agent response`
- TTS：`tts_chunk.text` 或 `tts_chunk.audio_b64`

流程：

1. 音频过程中按阈值发 `STT_PARTIAL`。
2. 停止收音后发 `STT_FINAL`。
3. 将 transcript 送入 Agent；结果经过安全/交互策略后以 TTS 指令下发。

存储与输出：

- 回合事件写 `lifelog_events`（如 `voice_turn`）。
- 会话消息写到 session JSONL 与分层记忆。

关键代码：

- `nanobot/hardware/runtime/connection.py:1199`
- `nanobot/hardware/runtime/connection.py:455`
- `nanobot/hardware/runtime/connection.py:631`
- `nanobot/hardware/runtime/connection.py:701`
- `nanobot/agent/loop.py:592`

### 3.4 图片原始数据
数据字段：

- `image_base64`（兼容 `imageBase64/image`）
- `mime`
- `question/prompt`

流程：

1. `image_ready` 时 Runtime 调用 lifelog 入队。
2. `LifelogService` 异步 worker 消费队列，进入视觉流水线。
3. 图片字节保存为资产 URI（`asset://...`）并记录 hash/dedup 状态。

存储与输出：

- 表：`lifelog_images`
- 文件：`ImageAssetStore` 管理的图片文件（带清理策略）

关键代码：

- `nanobot/hardware/runtime/connection.py:1359`
- `nanobot/api/lifelog_service.py:294`
- `nanobot/api/lifelog_service.py:412`
- `nanobot/vision/image_assets.py:52`
- `nanobot/storage/sqlite_lifelog.py:86`

### 3.5 图片结构化多模态数据
数据字段：

- `summary`
- `objects`
- `ocr`
- `risk_hints`
- `actionable_summary`
- `risk_level/risk_score/confidence`

流程：

1. 图像去重（dhash 相似度）。
2. 分析器输出结构化内容（可解析 JSON）。
3. 写 `lifelog_contexts` 并建立向量索引 metadata。
4. 生成 `image_ingested` 事件，payload 中携带 `structured_context`。

存储与查询：

- 表：`lifelog_contexts`
- 索引：向量索引（chroma/qdrant/内存回退）
- 查询：`/v1/lifelog/query` 支持对象/OCR/风险过滤

关键代码：

- `nanobot/vision/pipeline.py:38`
- `nanobot/vision/pipeline.py:142`
- `nanobot/vision/pipeline.py:154`
- `nanobot/api/lifelog_service.py:454`
- `nanobot/storage/sqlite_lifelog.py:98`

### 3.6 文本对话与长上下文记忆
数据字段：

- 会话历史（user/assistant）
- 长期记忆（`MEMORY.md/HISTORY.md`）
- 本地语义事实（`SEMANTIC.json`）
- 本地情节记忆（`EPISODIC.jsonl`）
- lifelog 检索命中（含 `structured_context`）

流程：

1. 每轮对话后 `record_turn` 记录 profile/episodic/semantic。
2. 新轮次构建 prompt 时，融合本地记忆 + lifelog 语义检索。
3. 会话过长触发 consolidate，将历史摘要写入长期记忆文件。

存储与输出：

- 会话 JSONL：`~/.nanobot/sessions/*.jsonl`
- 工作区记忆文件：`memory/` 下多文件

关键代码：

- `nanobot/agent/loop.py:390`
- `nanobot/agent/loop.py:592`
- `nanobot/agent/loop.py:783`
- `nanobot/agent/memory.py:224`
- `nanobot/agent/memory.py:260`
- `nanobot/agent/memory.py:375`
- `nanobot/session/manager.py:131`

### 3.7 遥测数据（含 IMU 潜在承载）
数据字段：

- `telemetry`（任意字典）

流程：

1. `telemetry` 事件进入 Runtime。
2. merge 到 `session.telemetry`。
3. 记录 lifelog `telemetry` 事件。
4. 注入 Agent runtime context（供推理时参考）。

存储与输出：

- `device_sessions.telemetry_json`
- `lifelog_events.payload.telemetry`

关键代码：

- `nanobot/hardware/runtime/connection.py:242`
- `nanobot/hardware/runtime/session_manager.py:113`
- `nanobot/hardware/runtime/connection.py:1302`
- `nanobot/storage/sqlite_lifelog.py:143`

### 3.8 任务与设备控制数据
数据字段：

- 数字任务：`task_id/goal/status/steps/result/error`
- 推送队列：设备侧状态更新消息
- 设备操作：`operation_id/op_type/payload/status/ack`

流程：

1. 语音可路由 digital task 执行。
2. 任务异步运行，状态可推送设备并带重试。
3. 控制面可 dispatch 设备操作并接收 ack，回写状态。

存储与查询：

- 表：`digital_tasks`、`digital_task_push_queue`、`device_operations`
- 接口：`/v1/digital-task*`、`/v1/device/ops*`

关键代码：

- `nanobot/hardware/runtime/connection.py:493`
- `nanobot/api/digital_task_service.py:184`
- `nanobot/api/digital_task_service.py:314`
- `nanobot/storage/sqlite_tasks.py:64`
- `nanobot/storage/sqlite_tasks.py:86`
- `nanobot/storage/sqlite_lifelog.py:202`
- `nanobot/api/hardware_server.py:483`

### 3.9 安全审计、思维追踪与可观测指标
数据字段：

- 安全审计：`safety_policy` 事件
- 追踪：`thought_trace`
- 观测：`healthy/metrics/thresholds`

流程：

1. 运行时安全决策、关键事件写入 lifelog。
2. trace 记录可按 `trace_id/session_id` 回放。
3. observability 采样写历史，用于健康趋势查询。

存储与查询：

- 表：`thought_traces`、`lifelog_events`（observability 事件）、`runtime_observability_samples`
- 接口：`/v1/lifelog/safety*`、`/v1/lifelog/thought_trace*`、`/v1/runtime/observability*`

关键代码：

- `nanobot/api/lifelog_service.py:647`
- `nanobot/api/lifelog_service.py:1086`
- `nanobot/storage/sqlite_lifelog.py:236`
- `nanobot/storage/sqlite_lifelog.py:923`
- `nanobot/api/hardware_server.py:638`
- `nanobot/storage/sqlite_observability.py:45`

---

## 4. IMU 当前结论（重点）
当前代码未实现专门 IMU 数据模型与专用存储结构：

- 无 `imu/accelerometer/gyroscope/magnetometer` 专项 schema、解析器、索引与查询接口。
- IMU 现阶段只能作为 `telemetry` 子字段透传与留存。

这意味着：

- 可以先传、先存、先参与上下文推理。
- 但不能高效做“按 IMU 字段维度”的结构化检索、聚合统计与规则触发。

---

## 5. 建议的下一步（针对 IMU）

1. 协议层：在 `telemetry` 下固化 IMU 标准字段（单位、坐标系、采样频率、时间戳）。
2. 存储层：新增 `imu_samples` 表（或时序库）并建立 `device_id/session_id/ts` 索引。
3. 服务层：新增 IMU 查询与聚合 API（窗口统计、峰值、异常事件）。
4. 策略层：将 IMU 规则接入风险提示与告警事件流（跌倒、剧烈震动、长时间静止）。


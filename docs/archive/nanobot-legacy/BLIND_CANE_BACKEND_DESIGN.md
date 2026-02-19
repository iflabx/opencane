# 多模态盲杖后端改造设计（基于 nanobot）

## 0. 设计原则

本项目是“辅助出行”场景，设计优先级建议固定为：

1. 安全性 > 可用性 > 智能性
2. 低延迟 > 高复杂度功能
3. 可解释 > 过度拟人化表达
4. 可降级 > 单点高性能依赖

特别强调：

- 后端不得输出“确定性导航指令”当其置信度不足
- 风险识别模块必须支持故障降级（保守提醒）


## 1. 产品目标与边界

目标：

- 语音对话：实时、可打断、低延迟问答
- 长上下文记忆：长期用户偏好、场景化记忆、提醒策略
- 图片多模态识别：环境描述、OCR、目标查找、风险提示

边界：

- 本文聚焦后端平台，不覆盖硬件传感器电路与固件
- 不把系统定义为“自动导航”，而是“辅助决策与感知增强”


## 2. 目标架构（逻辑视图）

```text
Blind Cane Device
  -> Realtime Gateway (WebSocket/gRPC)
      -> Audio Pipeline (VAD/ASR/TTS)
      -> Vision Pipeline (Detection/OCR/VLM)
      -> Agent Orchestrator (Intent/Tools/Policy)
      -> Memory Service (Session + Long-term + Vector)
      -> Safety Policy Engine
  -> Event Bus / Queue
  -> Storage (PostgreSQL + Object Storage + Vector DB + Redis)
  -> Caregiver Notification Service (optional)
```

### 2.1 分层职责

设备接入层：

- 接入音频流、图片帧、按键、定位、IMU、测距事件
- 设备鉴权、会话管理、断线重连

实时交互层：

- 流式语音处理
- 实时中断与恢复
- 对话状态机管理

多模态认知层：

- 图像多任务并行推理
- 语义融合与置信度聚合

策略与记忆层：

- 长期记忆读写与检索
- 风险分级与输出约束
- 提醒与主动任务调度


## 3. 核心用户场景（建议先实现）

场景 A：走路中即时问答

- 用户：按键后说“前面有什么？”
- 系统：语音识别 + 最近图像帧分析 + 风险摘要播报
- 输出：优先播报危险信息，再播报一般信息

场景 B：读字识别

- 用户：说“读一下这张纸”
- 系统：拍照 -> OCR -> 文本重排 -> TTS播报

场景 C：长期偏好记忆

- 用户：说“以后语速慢一点”
- 系统：写入 profile_memory，后续 TTS 自动应用

场景 D：紧急事件

- 用户：长按紧急按钮
- 系统：立即推送位置、时间、最近语音摘要给联系人


## 4. 语音对话设计

## 4.1 实时语音链路

推荐流程：

1. 设备上行 `audio_chunk`
2. 服务端 VAD 检测语音段
3. 流式 ASR 输出 partial/final transcript
4. Agent 根据最终文本 + 上下文生成回复
5. 流式 TTS 回传 `assistant_audio_chunk`
6. 支持 `interrupt` 中断当前播报并切换新轮对话

## 4.2 对话状态机

建议状态：

- `idle`
- `listening`
- `thinking`
- `speaking`
- `interrupted`
- `error_recovering`

状态机目标：

- 避免“边听边说”冲突
- 保障中断时资源释放完整

## 4.3 语音输出规范

- 短句优先，句长控制在 8~16 字为主
- 先说风险，再说说明
- 避免“可能、也许”堆叠，改为明确置信提示

示例：

- 推荐：“前方约两米有向下台阶，请减速并试探。”
- 避免：“我觉得前方可能大概有一些障碍，注意一下。”


## 5. 长上下文记忆设计

## 5.1 记忆分层

短期会话记忆：

- 每个会话最近 N 轮，现有 `SessionManager` 可复用

长期档案记忆（Profile）：

- 偏好：语速、语气、常用词
- 习惯：常出行时间、常去地点
- 无障碍偏好：提醒密度、风险播报阈值

情景事件记忆（Episodic）：

- “什么时候、在哪、发生了什么、如何处理”

语义记忆（Semantic）：

- 向量化检索，用于长跨度问答与个性化响应

## 5.2 写入策略（关键）

只写入高价值信息：

- 用户明确声明偏好
- 高频重复信息
- 安全相关历史事件

不写入：

- 一次性闲聊
- 敏感信息且未授权

## 5.3 检索策略

每轮检索预算建议：

- Profile：固定拉取
- Episodic：最近 7 天 + 地理相似场景
- Semantic：Top-K（3~8） + rerank

记忆注入到提示词时必须标注来源与时间，降低幻觉风险。


## 6. 图片多模态识别设计

## 6.1 能力模块

- 场景理解：道路、楼梯、电梯口、门、障碍物
- OCR：路牌、包装、票据、菜单、药品标签
- 目标检索：按属性找物（颜色/形状/类别）
- 风险识别：高低差、临时障碍、人车接近

## 6.2 推理编排

建议并行执行：

- `detector_task`
- `ocr_task`
- `vlm_reason_task`

汇总层做结果融合：

- 统一坐标系与置信度
- 冲突结果处理（高风险优先）
- 输出压缩为可播报格式

## 6.3 风险分级

- `P0` 立即危险：跌落风险、车辆逼近、强障碍
- `P1` 高风险：复杂路口、施工区域、拥挤地段
- `P2` 低风险：可绕行轻障碍
- `P3` 信息性：普通场景描述

播报顺序必须 `P0 -> P1 -> P2 -> P3`。

## 6.4 借鉴的图片管理闭环（来自参考实现）

为避免“只做识别，不做管理”，建议采用闭环：

1. 图片采集入队（设备拍照、关键帧、文档图像）
2. 预处理（缩放、去噪、哈希去重）
3. VLM 识别（图像 + 任务prompt）
4. 结构化落库（objects/ocr/risk/summary）
5. 向量化检索（以 `title/summary` 文本向量为主）
6. 活动化管理（时间线展示 + 资源关联）
7. 生命周期清理（按保留策略清理原图与中间结果）

关键借鉴点：

- 检索主链路采用“图转文后检索”优先，不强依赖原生图像向量检索
- 识别结果必须结构化，避免只存自由文本
- 识别、检索、展示、清理是一个完整产品闭环

## 6.5 视觉结果结构化 Schema（建议）

建议单帧/单图输出统一结构：

```json
{
  "frame_id": "img-001",
  "captured_at": "2026-02-12T12:00:00Z",
  "scene_summary": "室内走廊，前方有下行台阶",
  "risk_level": "P0",
  "risk_confidence": 0.86,
  "objects": [
    {"label": "stairs_down", "bbox": [0.42, 0.50, 0.25, 0.30], "confidence": 0.88}
  ],
  "ocr_items": [
    {"text": "出口 Exit", "bbox": [0.12, 0.08, 0.30, 0.10], "confidence": 0.93}
  ],
  "semantic_title": "前方下行台阶风险",
  "semantic_summary": "用户前方约1.5米出现下行台阶，建议立即减速停下确认。"
}
```

字段说明：

- `semantic_title/semantic_summary` 用于向量索引与历史检索
- `objects/ocr_items` 用于可解释与回放
- `risk_*` 用于实时播报和策略引擎


## 7. 安全策略引擎

## 7.1 双层策略

规则层（deterministic）：

- 基于置信度、风险等级、事件类型的硬规则

模型层（LLM policy）：

- 对回复做语义安全审查（是否有误导性动作建议）

## 7.2 强制规则示例

- 当视觉置信度 < 阈值且用户在移动中，禁止给出方向性细指令
- 当出现 `P0` 风险，强制插入“停止-确认-再行动”话术
- 连续识别冲突时，触发“建议寻求人协助”降级策略

## 7.3 审计

每轮输出写入安全审计日志：

- 输入摘要
- 识别结果与置信度
- 风险等级
- 最终回复与策略命中项


## 8. 与现有 nanobot 的改造映射

可复用：

- Agent 循环：`nanobot/agent/loop.py`
- 上下文构造：`nanobot/agent/context.py`
- 会话管理：`nanobot/session/manager.py`
- 定时提醒：`nanobot/cron/service.py`
- 心跳主动任务：`nanobot/heartbeat/service.py`
- 现有语音转写基础：`nanobot/providers/transcription.py`

建议新增目录：

- `nanobot/hardware/runtime/`
- `nanobot/hardware/adapter/`
- `nanobot/audio/asr_service.py`
- `nanobot/audio/tts_service.py`
- `nanobot/vision/pipeline.py`
- `nanobot/memory/store.py`
- `nanobot/memory/retriever.py`
- `nanobot/safety/policy_engine.py`
- `nanobot/safety/rulebook.py`
- `nanobot/api/hardware_server.py`

建议新增工具（供 Agent 调用）：

- `vision_analyze`
- `memory_query`
- `memory_write`
- `safety_check`
- `notify_emergency`


## 9. API 与事件契约（草案）

## 9.1 实时流接口

- `WS /v1/stream/session/{session_id}`

客户端上行事件：

- `audio_chunk`
- `image_frame`
- `button_event`
- `gps_event`
- `interrupt`

服务端下行事件：

- `asr_partial`
- `asr_final`
- `assistant_text`
- `assistant_audio_chunk`
- `risk_alert`
- `system_state`

## 9.2 事件示例

```json
{
  "type": "audio_chunk",
  "device_id": "cane-001",
  "session_id": "sess-abc",
  "seq": 1024,
  "sample_rate": 16000,
  "codec": "pcm16",
  "data_b64": "..."
}
```

```json
{
  "type": "risk_alert",
  "session_id": "sess-abc",
  "level": "P0",
  "message": "前方约1.5米有向下台阶，请立即减速并停下确认。",
  "confidence": 0.86
}
```

## 9.3 HTTP 管理接口

- `POST /v1/vision/analyze`
- `POST /v1/memory/query`
- `POST /v1/memory/write`
- `POST /v1/emergency/trigger`
- `GET /v1/session/{id}/timeline`

## 9.4 图片管理接口（新增建议）

- `POST /v1/image/enqueue`
- 输入：`device_id + session_id + image + metadata`
- 作用：把原图放入异步处理队列

- `POST /v1/image/dedup/check`
- 输入：`dhash/phash`
- 输出：是否重复 + 近似候选

- `POST /v1/vector_search`
- 输入：`query + filters(session_id/time/risk_level)`
- 输出：关联图像语义结果（基于 `semantic_summary` 检索）

- `GET /v1/activity/timeline`
- 输出：按时间聚合的“图像+风险+语音事件”资源流


## 10. 数据模型与存储

建议组件：

- PostgreSQL：核心结构化数据
- 对象存储：音频、图片、回放片段
- 向量库：语义记忆检索
- Redis：实时状态、流式会话缓冲

核心表：

- `users`
- `devices`
- `sessions`
- `session_events`
- `memory_items`
- `vision_results`
- `safety_decisions`
- `emergency_events`

新增图片管理相关表建议：

- `image_raw_events`
- `image_processed_contexts`
- `activity_timeline`
- `media_retention_jobs`

`memory_items` 关键字段建议：

- `id`
- `user_id`
- `memory_type` (`profile|episodic|semantic`)
- `content`
- `embedding`
- `importance_score`
- `expires_at`
- `source_event_id`
- `created_at`

`image_processed_contexts` 关键字段建议：

- `id`
- `session_id`
- `device_id`
- `image_uri`
- `dhash`
- `phash`
- `scene_summary`
- `semantic_title`
- `semantic_summary`
- `risk_level`
- `risk_confidence`
- `objects_json`
- `ocr_json`
- `created_at`

存储策略建议：

- 原图存对象存储（冷数据可降级到低频存储）
- 结构化结果存 PostgreSQL
- `semantic_summary` 写入向量库用于跨时段检索


## 11. 可靠性与可观测性

## 11.1 关键 SLO

- 语音首字延迟 P95 < 800ms
- 语音问答端到端 P95 < 3s
- 图像分析首响应 P95 < 4s
- 核心可用性 > 99.9%

## 11.2 指标与日志

建议指标：

- ASR/TTS 延迟与失败率
- 视觉推理时延和置信度分布
- 风险命中率与误报率
- 中断次数与恢复成功率
- 图片去重命中率（dHash/pHash）
- VLM 结构化输出成功率（JSON parse success）
- 图片处理队列积压长度与耗时

建议日志：

- 结构化 JSON 日志
- 全链路 trace_id / session_id / device_id
- 安全决策审计日志独立存储


## 12. 分阶段实施路线图

Phase 1（2~4 周，MVP）：

- 新增 `blindcane` channel（WebSocket）
- 打通 ASR -> Agent -> TTS
- 打通图像分析（场景 + OCR）
- 基础风险分级与保守播报
- 落地“图片入队 -> VLM结构化 -> 向量索引”最小闭环

Phase 2（4~8 周）：

- 长期记忆（Profile + Episodic + Semantic）
- 记忆检索注入与压缩策略
- 应急联动基础版
- 活动时间线与图片资源管理
- dHash/pHash 去重与保留策略

Phase 3（8~12 周）：

- 多传感融合（GPS/IMU/测距）
- 个性化策略学习
- 监护端与运营后台
- 多模态历史检索（图像语义 + 风险事件 + 语音摘要）


## 13. 测试与验收

离线评测：

- 语音集：口音、噪声、走路场景
- 图像集：白天/夜晚/逆光/雨天/复杂街景
- 安全集：高风险障碍专项数据

在线灰度：

- 小样本封闭试点
- 人工回访与误导案例复盘
- 分阶段放量

验收建议：

- 语音问答成功率 > 90%
- 风险场景漏报率 < 2%
- 高风险误导率 < 1%
- 关键任务中断恢复成功率 > 98%


## 14. 当前项目下一步改造清单（可直接进入开发）

1. 以 `nanobot hardware serve` 为统一入口，固定硬件运行时启动与控制面端口
2. 在 `nanobot/hardware/runtime/` 与 `nanobot/hardware/adapter/` 定义实时事件协议与适配层
3. 在 `nanobot/agent/tools/` 增加 `vision_analyze`、`memory_query`、`memory_write`
4. 在 `nanobot/agent/loop.py` 增加回复前 `safety_check` 钩子
5. 新建 `nanobot/memory/` 子模块，落地长期记忆接口
6. 新建 `nanobot/vision/` 与 `nanobot/audio/` 服务封装
7. 增加 `tests/` 下的语音链路、视觉链路、安全策略测试
8. 增加 `nanobot/vision/image_store.py`（原图+哈希+生命周期）
9. 增加 `nanobot/vision/indexer.py`（`semantic_summary` 向量化索引）
10. 增加 `nanobot/vision/activity_timeline.py`（图像资源时间线聚合）


## 15. 开放问题（建议尽快确认）

1. 设备与后端的首版协议选 `WebSocket` 还是 `gRPC`？
2. 首版是否需要离线模式（本地ASR/TTS）？
3. 目标部署形态：单机一体化还是云端多服务？
4. 监管与隐私合规边界（音频与图像保留时长）？
5. 是否引入监护人 App 作为第一批功能？


## 16. 参考 MineContext 源码的实现级借鉴（深度版）

本节基于 `~/MineContext` 源码，不是概念复述，重点提炼可直接迁移到盲杖后端的实现方法。

### 16.1 图片处理闭环的关键实现点（源码级）

采集与入队：

- 路由层采用轻量入队接口，`/api/add_screenshot` 只做参数接收和入队触发：`/home/devuser/MineContext/opencontext/server/routes/screenshots.py`
- 入队时统一构造 `RawContextProperties`，明确 `content_format=IMAGE`、时间与来源：`/home/devuser/MineContext/opencontext/server/context_operations.py:72`
- 处理器路由通过 `ContextSource -> processor_name` 映射完成：`/home/devuser/MineContext/opencontext/managers/processor_manager.py:87`

异步批处理与背压：

- `ScreenshotProcessor` 内部用 `queue.Queue + background thread`，并用 `batch_size/batch_timeout` 控制吞吐：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:76`
- 这类“前台快入队，后台批处理”的模型很适合盲杖实时场景，能降低上行抖动影响。

预处理与去重：

- 图片先可选缩放，再做感知哈希近似去重：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:158`
- 去重用 `dHash`（函数名叫 `calculate_phash`，实现是 `imagehash.dhash`）+ 汉明距离阈值：`/home/devuser/MineContext/opencontext/utils/image.py:33`
- 维护最近窗口 `deque` 做实时去重，命中可删除重复原图：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:130`

VLM 多模态调用：

- 图像转 base64 后按 `image_url` data URI 注入消息体，同时携带文本 prompt：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:260`
- VLM 输出要求结构化 JSON（`items`），解析失败直接按错误路径处理：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:292`

结构化与语义索引：

- 每个识别项落成 `ProcessedContext`，向量化内容主轴是 `title + summary` 文本：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:575`
- 不是以图像向量为主，而是“图转文后检索”主导，这对盲杖查询（语音问答）更稳定。

语义合并与上下文压缩：

- 同 `context_type` 的新旧项会走 LLM merge，输出 `merged/new`，并可删除被合并旧记录：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:303`
- merge 后并行做实体刷新和 embedding，避免串行瓶颈：`/home/devuser/MineContext/opencontext/context_processing/processor/screenshot_processor.py:452`

向量库组织与检索：

- Chroma/Qdrant 都按 `context_type` 建独立 collection：`/home/devuser/MineContext/opencontext/storage/backends/chromadb_backend.py:164`、`/home/devuser/MineContext/opencontext/storage/backends/qdrant_backend.py:60`
- 检索支持 filters（时间戳范围、字段匹配）：`/home/devuser/MineContext/opencontext/storage/backends/chromadb_backend.py:740`、`/home/devuser/MineContext/opencontext/storage/backends/qdrant_backend.py:487`
- 外部检索入口统一为 `/api/vector_search`：`/home/devuser/MineContext/opencontext/server/routes/context.py:117`

活动化管理（时间线）：

- 活动生成时会从代表上下文抽取图片资源，写入 `activity.resources`：`/home/devuser/MineContext/opencontext/context_consumption/generation/realtime_activity_monitor.py:279`
- SQLite `activity` 表中 `resources`/`metadata` 使用 JSON 字段：`/home/devuser/MineContext/opencontext/storage/backends/sqlite_backend.py:126`
- 前端时间线按 `resources.type === image` 展示：`/home/devuser/MineContext/frontend/src/renderer/src/pages/screen-monitor/components/activitie-timeline-item.tsx:28`

生命周期清理：

- 桌面侧启动即触发、并每日定时清理旧截图（默认 15 天）：`/home/devuser/MineContext/frontend/src/main/index.ts:76`
- 清理逻辑按日期目录批量删除并统计释放空间：`/home/devuser/MineContext/frontend/src/main/services/ScreenshotService.ts:277`

### 16.2 文档/网页图片分支的高价值借鉴

页级路由策略：

- PDF/DOCX/MD 先按页判定是否“视觉页”，文本页直抽取，视觉页走 VLM：`/home/devuser/MineContext/opencontext/context_processing/processor/document_processor.py:339`
- 这是一种性价比很高的“视觉按需推理”策略，可显著降本控时延。

Markdown 图片统一纳管：

- Markdown 解析时同时抽取本地图片和远程图片并转 PIL 参与分析：`/home/devuser/MineContext/opencontext/context_processing/processor/document_converter.py:548`
- 对盲杖项目可迁移为“图像证据统一入口”（设备拍照、文档、网页图片共管）。

网页转文档再复用同链路：

- URL 可先转 PDF/Markdown，再进入同一文档处理器：`/home/devuser/MineContext/opencontext/context_capture/web_link_capture.py:212`
- 对盲杖可映射为“公告/地图说明/场馆导览文档”离线预处理链路。

## 17. 对 nanobot 的具体落地映射（按实现模块）

### 17.1 目录与职责建议

建议新增并落地以下模块（与 MineContext 闭环一一对应）：

- `nanobot/vision/image_ingest.py`
- `nanobot/vision/image_dedup.py`
- `nanobot/vision/vlm_parser.py`
- `nanobot/vision/context_merger.py`
- `nanobot/vision/vector_indexer.py`
- `nanobot/vision/timeline_service.py`
- `nanobot/vision/retention_service.py`
- `nanobot/vision/schemas.py`
- `nanobot/memory/longterm_store.py`
- `nanobot/memory/retriever.py`
- `nanobot/hardware/runtime/connection.py`
- `nanobot/hardware/adapter/ec600_mqtt.py`
- `nanobot/api/hardware_server.py`

对应关系：

- 入队与路由：映射 `ContextOperations + ProcessorManager`
- 去重与预处理：映射 `ScreenshotProcessor + utils/image.py`
- VLM 结构化：映射 `_process_vlm_single + _create_processed_context`
- 语义索引：映射 `vectorize(text=title+summary)` + vector backend
- 活动资源：映射 `activity.resources` 模式
- 生命周期：映射每日 cleanup 模式

### 17.2 与当前 nanobot 架构的挂接点

硬件运行时层：

- 复用 canonical 协议模型：`/home/devuser/nanobot/nanobot/hardware/protocol.py`
- 通过 `nanobot hardware serve` 启动 `runtime + adapter + control api`：`/home/devuser/nanobot/nanobot/cli/commands.py`

消息与会话层：

- 利用 `InboundMessage.media` 接收图像帧路径或对象存储 URI：`/home/devuser/nanobot/nanobot/bus/events.py:17`
- `SessionManager` 保留短期对话，长期记忆迁移到结构化存储：`/home/devuser/nanobot/nanobot/session/manager.py:61`

Agent 编排层：

- 在 `AgentLoop` 中插入“回复前 safety gate”与“视觉结果注入”：`/home/devuser/nanobot/nanobot/agent/loop.py:144`
- 扩展 tools：`vision_analyze`、`memory_query`、`memory_write`、`safety_check`

多模态输入层：

- 现有 `ContextBuilder` 已支持 `image_url(data URI)` 注入：`/home/devuser/nanobot/nanobot/agent/context.py:163`
- 盲杖后端建议改为“实时事件 + 异步图像处理结果回填”，而非每轮都内联大图。

## 18. 盲杖后端可执行技术方案（借鉴后增强）

### 18.1 统一图像事件模型

建议新增统一事件表 `image_events`：

- `id`
- `device_id`
- `session_id`
- `event_type` (`frame|photo|doc_image`)
- `image_uri`
- `dhash`
- `ingest_at`
- `status` (`queued|processing|done|failed|dedup_skipped`)
- `trace_id`

建议新增结构化结果表 `image_contexts`：

- `id`
- `event_id`
- `scene_summary`
- `semantic_title`
- `semantic_summary`
- `risk_level`
- `risk_confidence`
- `objects_json`
- `ocr_json`
- `raw_vlm_json`
- `created_at`

### 18.2 处理流水线（建议）

`ingest -> resize -> dhash_dedup -> vlm_parse_json -> normalize_schema -> vectorize(summary) -> index -> timeline_bind -> retention`

关键策略：

- 实时对话通路只读“最近已完成结果 + 风险最高结果”
- 识别失败不阻塞主链路，降级为“请再次拍摄/环境较暗”
- 去重命中写 `dedup_skipped` 事件，保留可观测性

### 18.3 长上下文记忆融合（视觉驱动）

写入规则：

- 仅将高价值视觉事件写入长期记忆：`risk_level in {P0,P1}` 或用户显式确认“记住这个”
- 其余只留短期缓存与时间线

查询规则：

- 语音问答先查 `profile memory`
- 再查最近时间窗视觉事件（例如 15 分钟）
- 最后做跨会话向量检索（`semantic_summary`）

### 18.4 安全与可解释输出

对外播报模板：

- 第一段：风险结论（等级 + 距离/方向 + 动作建议）
- 第二段：证据摘要（对象/OCR/置信度）
- 第三段：不确定性声明（低置信度时）

审计字段（每轮必落）：

- `model_name`
- `prompt_version`
- `risk_rules_hit`
- `final_message`
- `evidence_event_ids`
- `decision_latency_ms`

### 18.5 分阶段实施（实现优先级）

P0（2~3 周）：

- `blindcane` 通道 + 图像入队 + dHash 去重 + VLM JSON 结构化 + 风险播报
- `semantic_summary` 向量索引 + `/v1/vector_search`

P1（3~5 周）：

- LLM merge 压缩（按 `context_type/risk_type`）
- 活动时间线（图像资源 + 语音摘要 + 风险事件）
- 每日 retention 清理与统计

P2（持续）：

- 文档/网页图片纳管（页级视觉判定）
- 多源融合（图像 + IMU + 测距）与置信度校准
- 个性化安全阈值（基于用户偏好与历史）

# 基于 `nanobot` 实现 2026 创新点的后端开发方案（MVP：数字盲道 + 生命日志）

## 摘要
本方案以你已确认的方向为准：
- 范围：仅 `nanobot` 后端
- 首期重点：`OpenClaw式数字盲道` + `生成式生命日志`
- 部署：单体优先
- 存储：`SQLite + Chroma` 本地优先

目标是在当前仓库内新增一个“盲杖后端能力层”，让系统从聊天 Agent 升级为：
1. 可接收设备事件并进行多模态处理  
2. 可在云端执行“代操作任务”（数字盲道）  
3. 可沉淀与检索生命日志（图像/事件/语义）  
4. 可通过策略输出安全、可解释反馈  

## 一、创新点到实现项映射
1. 云定义硬件（对应后端能力）
- 实现设备接入协议与会话层，终端只上传事件与媒体，重计算在云端（本服务）完成。
2. Blind-Native 模型对齐（MVP简化）
- 先以“提示词策略 + 输出约束”替代训练闭环，定义视障原生输出模板。
3. 数字盲道（MVP核心）
- 新增“代操作任务”能力：将语音意图转成工具链执行任务（Web/API 自动化）。
4. 生命日志（MVP核心）
- 新增图像与事件入库、向量索引、时序回放与检索。
5. 自适应通信（MVP基础）
- 接口支持低频心跳帧与事件触发帧两种优先级，后端异步分流。
6. 混合主动交互（MVP基础）
- 新增风险播报策略与“沉默模式”控制字段（先做规则层，不做复杂学习）。

## 二、代码结构改造（决策已定）
当前代码已落地路径（与实现对齐）：
- `nanobot/api/hardware_server.py`：硬件控制 API 与调试入口
- `nanobot/api/vision_server.py`：视觉分析服务封装
- `nanobot/api/lifelog_service.py`：生命日志服务
- `nanobot/api/digital_task_service.py`：数字任务服务
- `nanobot/vision/pipeline.py`
- `nanobot/vision/dedup.py`
- `nanobot/vision/store.py`
- `nanobot/vision/indexer.py`
- `nanobot/vision/timeline.py`
- `nanobot/safety/policy.py`
- `nanobot/storage/sqlite_lifelog.py`
- `nanobot/storage/chroma_lifelog.py`
- `nanobot/storage/sqlite_tasks.py`
- `nanobot/hardware/runtime/*` + `nanobot/hardware/adapter/*`：统一协议运行时与 EC600 适配

关键入口说明（与现状一致）：
- 通过 `nanobot hardware serve` 启动盲杖后端运行时（而非单独 `blindcane` channel）
- 配置入口在 `config.hardware / config.vision / config.lifelog / config.digital_task / config.safety`

## 三、公共接口与协议（固定方案）
### 1. 设备实时接口
- 统一协议入口：`nanobot hardware serve`（适配 `ec600/mock/websocket`）
- 控制面 HTTP：`http://127.0.0.1:18792`（control API）
- 上行事件：
- `hello/heartbeat/listen_start/audio_chunk/listen_stop/abort/image_ready/telemetry`
- 下行事件：
- `hello_ack/ack/stt_final/tts_start/tts_chunk/tts_stop/task_update/close`

### 2. 管理与检索接口
- `POST /v1/lifelog/enqueue_image`
- `POST /v1/lifelog/query`
- `GET /v1/lifelog/timeline`
- `POST /v1/digital-task/execute`
- `GET /v1/digital-task/{task_id}`

### 3. 内部工具接口（供 Agent）
- `vision_analyze(frame_id|image_uri, mode)`
- `lifelog_query(query, time_range, top_k)`
- `digital_task(goal, constraints, channel_context)`

## 四、数据模型（固定字段）
SQLite 表：
1. `device_sessions`
- `session_id, device_id, started_at, ended_at, status`

2. `lifelog_events`
- `id, session_id, event_type, ts, payload_json, risk_level, confidence`

3. `lifelog_images`
- `id, session_id, image_uri, dhash, is_dedup, ts`

4. `lifelog_contexts`
- `id, image_id, semantic_title, semantic_summary, objects_json, ocr_json, risk_level, risk_score, ts`

5. `digital_tasks`
- `task_id, session_id, goal, status, steps_json, result_json, error, created_at, updated_at`

Chroma collection：
- `lifelog_semantic`
- 文档内容：`semantic_title + semantic_summary`
- metadata：`session_id, ts, risk_level, image_id`

## 五、核心流程（实现级）
### 1. 生命日志闭环
1. `image_frame` 入站
2. `dedup.py` 计算 dHash 并判重
3. 新图走 `vision/pipeline.py`（VLM结构化）
4. 结构化结果写 `lifelog_contexts`
5. `indexer.py` 写入 Chroma
6. `timeline.py` 聚合时间线输出

### 2. 数字盲道闭环
1. 用户语音意图进入 `digital_task` 工具
2. 工具选择执行路径：
- 优先调用 MCP 工具（如果已配置）
- 否则调用现有 web/exec 工具链
3. 状态回写 `digital_tasks`
4. 输出 `task_status` 与可播报摘要

### 3. 安全播报闭环
1. 视觉/任务结果进入 `safety/policy.py`
2. 规则分级：`P0/P1/P2/P3`
3. 低置信度时输出保守话术，不给方向性强指令
4. 写审计日志（输入摘要、证据、命中规则、最终话术）

## 六、分阶段开发计划（可直接执行）
### Phase 1（第1周）：接口与骨架
- 建立硬件运行时（adapter + canonical protocol）与基础 control API
- 建立 SQLite 表与 Chroma 初始化逻辑
- 新增三个 Agent 工具骨架

### Phase 2（第2周）：生命日志 MVP
- 完成图片入队、dHash 去重、结构化落库
- 完成向量索引与 `lifelog_query` 检索
- 完成时间线接口

### Phase 3（第3周）：数字盲道 MVP
- 完成 `digital_task` 执行器（MCP优先，web/exec回退）
- 完成任务状态机与结果回写
- 加入中断与超时控制

### Phase 4（第4周）：安全与联调
- 接入 `safety policy` 回复前钩子
- 完成端到端联调（设备模拟输入）
- 完成验收测试与文档

## 七、测试与验收标准
### 单元测试
- `dedup`：同图/近似图判重正确率
- `lifelog_query`：时间过滤 + 向量召回正确性
- `digital_task`：成功、失败、超时、取消状态流转
- `safety_policy`：低置信度降级规则命中

### 集成测试
- WS 连续发送 `image_frame + intent_command`，验证：
- 生命周期落库完整
- 可检索历史语义
- 任务执行结果可追踪
- 风险播报可解释

### MVP 验收指标
- 图像入队到结构化结果 P95 < 4s
- 语义检索命中率（人工评审）> 80%
- 数字任务成功率（受控场景）> 85%
- 高风险错误指令率 < 1%

## 八、发布与观测
- 日志字段统一：`trace_id, session_id, device_id, task_id`
- 指标：
- lifelog 入队速率、去重率、处理时延
- vector 查询耗时、命中率
- digital_task 成功率、平均步数、失败原因分布
- 安全策略命中次数与降级次数
- 发布策略：
- 本地单机灰度
- 小样本设备联调
- 放量前冻结接口版本为 `v1`

## 九、明确假设与默认值
- 默认只实现后端，不改硬件固件代码。
- 默认使用 `SQLite + Chroma`，后续可迁移 `Postgres + Qdrant`。
- 默认采用规则式 Blind-Native 输出约束，不做模型再训练。
- 默认数字盲道优先走 MCP 工具，缺失时回退现有工具链。
- 默认先支持中文语音指令与中文播报模板。

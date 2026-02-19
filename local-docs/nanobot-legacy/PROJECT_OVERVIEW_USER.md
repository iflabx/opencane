# 项目综述（面向使用者）

更新时间：2026-02-19

## 1. 这是什么项目

这是一个“**AI Agent 平台 + 智能盲杖后端**”的一体化系统。

你可以把它理解为两层能力叠加：

1. 通用 AI 助手能力（多模型、多工具、多渠道、多会话记忆）
2. 智能硬件后端能力（设备接入、语音对话、图像多模态、长记忆、数字任务、安全治理）

它的目标不是只做聊天，而是把“盲杖设备 -> 实时理解 -> 安全反馈 -> 任务执行 -> 可追溯记忆”串成闭环。

---

## 2. 一图看懂整体架构

```text
智能盲杖/终端
  -> (WebSocket / MQTT / Mock)
适配层 Adapter
  -> 统一语义协议 Canonical Envelope
运行时编排 Runtime Core
  -> 语音链路(STT/Agent/TTS)
  -> 图像链路(VLM/Lifelog)
  -> 数字任务链路(Task Orchestrator)
策略层
  -> 安全策略(Safety)
  -> 交互策略(Interaction)
控制与运维层
  -> Control API / Device Ops / Auth / 限流 / 防重放
  -> Observability 指标与历史趋势
数据层
  -> SQLite(事件/会话/任务/设备)
  -> 向量索引(Chroma/Qdrant)
  -> 图片资产文件存储
```

---

## 3. 核心功能清单（用户可感知能力）

1. 语音对话：支持打断、部分转写、最终转写、语音播报
2. 长上下文记忆：融合文件记忆 + 本地语义/情节记忆 + lifelog 检索
3. 图片多模态识别：图像理解、结构化结果、时间线与语义检索
4. 数字任务执行：创建任务、异步执行、状态回推、离线补发
5. 设备管理：注册/绑定/激活/吊销，设备操作下发与回执
6. 安全治理：风险降级、保守措辞、审计可追溯
7. 可观测性：语音链路时延、失败率、离线率、队列健康度
8. 控制面扩展：远端策略下发、设备级工具权限控制
9. 软联调能力：无硬件可先开发、模拟、回放、契约验证

---

## 4. 每个功能如何实现

## 4.1 语音对话（实时）

### 用户侧体验
1. 说话开始后可实时看到/收到 partial 文本
2. 说完后得到完整理解和语音回复
3. 回复过程中再次说话可“打断”（barge-in）

### 技术实现机制
1. 设备上报 `listen_start -> audio_chunk -> listen_stop`
2. 音频管线做三件事：
   - 乱序重排（抖动窗口）
   - VAD 语音段过滤（含 prebuffer）
   - 分段文本/音频聚合
3. `listen_stop` 后优先使用显式 transcript；没有则走 STT 转写
4. STT provider 启动时按优先级选择：`Groq -> OpenAI -> 自定义 OpenAI 兼容端`
5. Agent 生成回复后进入 TTS：
   - `device_text`：文本分块下发给设备播报
   - `server_audio`：服务端先合成音频，再分片下发
6. 若处于播报状态又收到 `listen_start`，运行时立即发送 `tts_stop(aborted=true)` 完成打断

### 质量与观测
1. 记录 voice turn 总时延、STT 时延、Agent 时延
2. 统计成功/失败率，支持阈值告警

---

## 4.2 图片多模态识别与 Lifelog

### 用户侧体验
1. 拍照后得到场景描述与安全提示
2. 可按语义检索过去“看过什么”
3. 可按时间线回放关键事件

### 技术实现机制
1. 图片先进入异步 ingest 队列，不阻塞主链路
2. 队列支持三种溢出策略：`reject / wait / drop_oldest`
3. 入库前先做近重复检测：
   - 多哈希（`dhash + blake2`）
   - 汉明距离阈值判断
4. 非重复图片触发分析：
   - 调用视觉模型（VLM）
   - 统一抽取结构化字段：objects、OCR、risk_hints、actionable_summary、risk_level
5. 存储分层：
   - 图片资产文件（按会话+日期存放，自动保留上限）
   - SQLite（图像、上下文、事件、追踪）
   - 向量索引（Chroma/Qdrant）用于语义检索
6. 查询支持结构化过滤：
   - 是否包含目标物/OCR/风险提示
   - 包含关键词过滤
   - 风险等级过滤

### 质量与观测
1. 监控 ingest queue 深度、利用率、拒绝数、丢弃数、平均处理时延
2. 可查看结构化上下文与安全事件

---

## 4.3 长上下文记忆（Long Context Memory）

### 用户侧体验
1. 助手可记住长期偏好与身份信息
2. 可回忆近期事件与跨轮次上下文
3. 在盲杖场景中能结合历史图像与事件给出更连贯回答

### 技术实现机制
1. 本地文件记忆：`MEMORY.md + HISTORY.md`
2. 分层记忆：
   - 语义记忆（偏好/身份等事实）
   - 情节记忆（每轮对话摘要）
   - lifelog 记忆（图像与运行事件）
3. 每轮回答前，统一检索并注入提示词上下文：
   - 本地语义命中
   - 本地情节命中
   - lifelog 语义命中（含结构化片段）
4. 超长会话自动触发 memory consolidation，把旧对话整理入长期记忆

---

## 4.4 数字任务执行（OpenClaw-like 任务链路）

### 用户侧体验
1. 可创建“帮我预约/挂号/查询”等异步任务
2. 任务状态会持续播报/推送（已创建、执行中、完成、失败、超时）
3. 掉线后重连可自动补发未送达状态

### 技术实现机制
1. 任务进入持久化状态机：`pending -> running -> success/failed/timeout/canceled`
2. 执行器采用两阶段策略：
   - Stage 1：优先 MCP 工具路径
   - Stage 2：回退到 `web_search/web_fetch/exec`
3. 支持并发上限、超时控制、失败回写、步骤轨迹记录
4. 支持同设备“新任务打断旧任务”（interrupt_previous）
5. 设备推送失败时进入 push queue，按重试退避策略重发
6. 服务重启后自动恢复 unfinished 任务

---

## 4.5 设备接入与协议适配

### 用户侧体验
1. 可以接多种接入方式，不绑死单一芯片协议
2. 硬件协议迭代时，业务逻辑无需大改

### 技术实现机制
1. 采用统一语义协议 `Canonical Envelope`（事件/命令标准化）
2. 适配层可替换：
   - `MockAdapter`（仿真）
   - `WebSocketAdapter`（通用）
   - `EC600MQTTAdapter`（蜂窝模组场景）
3. EC600 适配内置：
   - 控制/音频 topic 分流
   - 音频帧头解析（16-byte header + payload）
   - 控制指令离线缓冲与重放窗口

---

## 4.6 设备管理与设备操作（Device Ops）

### 用户侧体验
1. 支持设备注册、绑定、激活、吊销
2. 可向设备下发操作（配置、工具调用、OTA 计划）
3. 可追踪每个操作是否已发送、已确认、失败

### 技术实现机制
1. 设备身份状态持久化：`registered / bound / activated / revoked`
2. 运行时可配置“是否强制设备鉴权”
3. 鉴权失败时立即关闭会话并记录审计事件
4. 设备操作支持全链路状态：`queued -> sent -> acked/failed/canceled`

---

## 4.7 安全策略（Safety）与交互策略（Interaction）

### 用户侧体验
1. 不确定或高风险场景下，回答会自动变得更保守
2. 高风险内容会有“先停下/注意安全”前缀
3. 夜间和低优先级消息可自动静默

### 技术实现机制
1. Safety Policy：
   - 风险级别推断（P0~P3）
   - 低置信度降级为保守模板
   - 冲突方向指令拦截
   - 输出长度控制
2. Interaction Policy：
   - 情感化前缀（高风险/低置信度）
   - 主动提示追加（如视觉结果后补充行动建议）
   - 静默策略（低优先级/安静时段）
3. 所有策略决策都会写入审计事件，支持复盘

---

## 4.8 控制 API 安全与治理

### 用户侧体验
1. 管理接口可加鉴权，避免未授权访问
2. 可防止高频刷接口与重放攻击

### 技术实现机制
1. 鉴权：`Authorization: Bearer` 或 `X-Auth-Token`
2. 限流：滑动窗口 + burst（按请求身份）
3. 防重放：`nonce + timestamp` 校验窗口
4. 大包保护：控制请求体大小上限（默认 12MB）

---

## 4.9 可观测性与运维

### 用户侧体验
1. 可实时看到系统是否健康
2. 可看历史趋势，不只看单次快照

### 技术实现机制
1. 实时指标：
   - 任务失败率
   - 安全降级率
   - 设备离线率
   - ingest 队列利用率
   - 语音链路延迟/失败率
2. 历史存储优先级：
   - 专用 observability SQLite
   - 回落到 lifelog SQLite
   - 再回落到内存
3. 支持时间窗口聚合与桶化趋势输出

---

## 4.10 远端控制面（Control Plane）

### 用户侧体验
1. 可在不重启主服务的情况下调整部分运行策略
2. 可按设备动态下发工具权限

### 技术实现机制
1. 远端拉取运行配置 + 设备策略
2. 本地缓存与过期控制，远端失败时可用 stale cache/fallback
3. 设备策略可动态控制工具 allow/deny 列表

---

## 4.11 通用 AI Agent 能力（项目基础）

### 用户侧体验
1. 同一套 Agent 可接 Telegram/Slack/Email/QQ 等多渠道
2. 支持文件、Web、Shell、MCP 工具扩展

### 技术实现机制
1. MessageBus 解耦通道与 Agent 执行
2. Agent Loop 支持工具调用迭代、子任务、会话持久化
3. 模型接入通过 LiteLLM Provider 统一适配多家模型

---

## 5. 对外 API（主要）

## 5.1 运行时与观测
1. `GET /v1/runtime/status`
2. `GET /v1/runtime/observability`
3. `GET /v1/runtime/observability/history`

## 5.2 设备管理与操作
1. `POST /v1/device/register`
2. `POST /v1/device/bind`
3. `POST /v1/device/activate`
4. `POST /v1/device/revoke`
5. `GET /v1/device/binding`
6. `POST /v1/device/ops/dispatch`
7. `POST /v1/device/ops/{operation_id}/ack`
8. `GET /v1/device/ops`
9. `POST /v1/device/event`（软联调用）

## 5.3 Lifelog 与多模态
1. `POST /v1/lifelog/enqueue_image`
2. `POST /v1/lifelog/query`
3. `GET /v1/lifelog/timeline`
4. `GET /v1/lifelog/safety`
5. `GET /v1/lifelog/safety/stats`
6. `POST /v1/lifelog/thought_trace`
7. `GET /v1/lifelog/thought_trace`
8. `GET /v1/lifelog/thought_trace/replay`

## 5.4 数字任务
1. `POST /v1/digital-task/execute`
2. `GET /v1/digital-task/{task_id}`
3. `POST /v1/digital-task/{task_id}/cancel`
4. `GET /v1/digital-task`
5. `GET /v1/digital-task/stats`

---

## 6. 部署与运行要点

1. 启动命令：`nanobot hardware serve --adapter ec600 --logs`
2. 模型层通过 LiteLLM 库实现统一接入（项目依赖里已声明 `litellm`）
3. EC600 MQTT 适配依赖 `paho-mqtt`（项目依赖已声明）
4. 可按配置开启/关闭：vision、lifelog、digital_task、safety、interaction、control-plane

---

## 7. 当前成熟度与边界

## 7.1 已具备
1. 后端主链路完整：语音、图像、记忆、任务、安全、观测
2. 软联调可用：Mock、事件注入、回放与契约测试
3. 控制 API 安全基线已具备：鉴权、限流、防重放

## 7.2 仍依赖硬件侧信息
1. 最终 Topic/字段冻结
2. 实机音频帧头与链路参数核验
3. 蜂窝网络下心跳/重连/超时参数最终定版

---

## 8. 结论

当前系统已经是一个可运行、可观测、可扩展的“多模态盲杖后端基础平台”。

在没有最终硬件接口文档的阶段，也可以先完成后端开发与软联调；待硬件协议冻结后，通过适配层与参数收口即可进入实机联调与上线阶段。

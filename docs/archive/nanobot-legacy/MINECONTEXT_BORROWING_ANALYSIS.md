# MineContext 可借鉴能力清单（面向 nanobot 盲杖后端）

更新时间：2026-02-17

## 目标

基于 `~/MineContext`，提炼可迁移到当前 `nanobot` 项目的实现模式，重点支持：

- 语音对话
- 长上下文记忆
- 图片多模态识别与管理

## 借鉴点（按优先级）

1. `P0` 图片异步入队 + 批处理背压链路  
   参考：`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:76`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:172`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:184`
2. `P0` 近似去重（哈希 + 阈值 + 可选删除）  
   参考：`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:114`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:131`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:137`
3. `P0` VLM 结构化协议（图 + 文输入，JSON 输出）  
   参考：`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:260`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:280`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:292`、`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:297`
4. `P0` 图转文语义索引主链（`title + summary` 向量化）  
   参考：`~/MineContext/opencontext/context_processing/processor/screenshot_processor.py:575`、`~/MineContext/opencontext/server/routes/context.py:117`
5. `P0` 向量后端双实现 + 过滤检索（Chroma/Qdrant）  
   参考：`~/MineContext/opencontext/storage/backends/chromadb_backend.py:551`、`~/MineContext/opencontext/storage/backends/chromadb_backend.py:740`、`~/MineContext/opencontext/storage/backends/qdrant_backend.py:337`、`~/MineContext/opencontext/storage/backends/qdrant_backend.py:487`
6. `P1` 活动时间线资源绑定（代表性图片绑定 activity）  
   参考：`~/MineContext/opencontext/context_consumption/generation/realtime_activity_monitor.py:81`、`~/MineContext/opencontext/context_consumption/generation/realtime_activity_monitor.py:92`、`~/MineContext/opencontext/context_consumption/generation/realtime_activity_monitor.py:279`、`~/MineContext/opencontext/storage/backends/sqlite_backend.py:126`、`~/MineContext/opencontext/storage/backends/sqlite_backend.py:739`
7. `P1` 生命周期清理（保留策略 + 定时清理）  
   参考：`~/MineContext/frontend/src/main/index.ts:76`、`~/MineContext/frontend/src/main/index.ts:100`、`~/MineContext/frontend/src/main/services/ScreenshotService.ts:277`、`~/MineContext/frontend/src/main/services/ScreenshotService.ts:321`
8. `P1` 可观测性（token/阶段耗时/数据趋势/错误）  
   参考：`~/MineContext/opencontext/monitoring/monitor.py:120`、`~/MineContext/opencontext/monitoring/monitor.py:133`、`~/MineContext/opencontext/monitoring/monitor.py:337`、`~/MineContext/opencontext/monitoring/monitor.py:487`、`~/MineContext/opencontext/server/routes/monitoring.py:23`
9. `P1` 文档多模态混合策略（视觉页走 VLM，文本页直抽取）  
   参考：`~/MineContext/opencontext/context_processing/processor/document_processor.py:312`、`~/MineContext/opencontext/context_processing/processor/document_processor.py:365`、`~/MineContext/opencontext/context_processing/processor/document_processor.py:419`、`~/MineContext/opencontext/context_processing/processor/document_converter.py:142`
10. `P2` 会话与“思考轨迹”持久化（可解释与回放）  
    参考：`~/MineContext/opencontext/storage/backends/sqlite_backend.py:1321`、`~/MineContext/opencontext/storage/backends/sqlite_backend.py:1548`、`~/MineContext/opencontext/storage/backends/sqlite_backend.py:1907`

## 与 nanobot 现状映射

1. 已具备多模态消息注入基础（`image_url(data URI)`）  
   参考：`nanobot/agent/context.py:164`
2. 已具备统一模型接入层（LiteLLM）  
   参考：`nanobot/providers/litellm_provider.py:15`
3. 当前长期记忆为文件型，建议升级为结构化 + 向量检索  
   参考：`nanobot/agent/memory.py:8`
4. 已具备心跳调度，可挂活动总结与主动提醒  
   参考：`nanobot/heartbeat/service.py:102`

## 建议迁移顺序

1. 先落地 `P0`：图片入队、去重、VLM 结构化、向量检索接口
2. 再落地 `P1`：时间线资源、保留策略、监控面板
3. 最后落地 `P2`：会话级思考轨迹与回放能力


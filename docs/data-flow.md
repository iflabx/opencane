# 关键数据流

## 1. 语音对话链路

1. 设备上报 `listen_start/audio_chunk/listen_stop`
2. 音频管线执行 jitter 重排、VAD、分段聚合
3. 无显式 transcript 时调用 STT
4. Agent 生成回复
5. TTS 以 `device_text` 或 `server_audio` 下发
6. 若播报中收到新 `listen_start`，触发打断

## 2. 图像 Lifelog 链路

1. `POST /v1/lifelog/enqueue_image` 入队
2. 异步 worker 执行分析、去重、结构化提取
3. 图片资产落盘，结构化结果入 SQLite
4. 语义向量入索引库
5. 通过 query/timeline/safety 接口检索

## 3. 数字任务链路

1. `POST /v1/digital-task/execute` 创建任务
2. 执行器优先 MCP，失败后回退 Web/Exec
3. 状态机持续更新并写入 SQLite
4. 任务状态可查询、统计、取消
5. 设备离线时状态回推进入重试队列

## 4. 观测与留痕链路

1. 运行时汇总 voice/queue/task/safety 指标
2. `GET /v1/runtime/observability` 实时评估
3. 历史样本持久化到 observability SQLite
4. 用于阈值监控和事后分析

# Digital Task API

## 1. 任务接口

- `POST /v1/digital-task/execute`
- `GET /v1/digital-task/{task_id}`
- `POST /v1/digital-task/{task_id}/cancel`
- `GET /v1/digital-task`
- `GET /v1/digital-task/stats`

## 2. 执行请求最小示例

```json
{
  "goal": "帮我查询今天上海天气",
  "session_id": "task-session-001"
}
```

常用可选字段：

- `task_id`
- `timeout_seconds`
- `device_id`
- `notify`（状态推送）
- `speak`（语音播报状态）
- `interrupt_previous`（同设备新任务打断旧任务）

## 3. 状态机

- `pending`
- `running`
- `success`
- `failed`
- `timeout`
- `canceled`

## 4. 执行策略

任务执行默认两阶段：

1. 优先 MCP 工具
2. 回退 Web/Exec 工具

## 5. 取消示例

```bash
curl -X POST http://127.0.0.1:18792/v1/digital-task/<task_id>/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"manual_cancel"}'
```

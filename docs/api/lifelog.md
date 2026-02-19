# Lifelog API

## 1. 图像入库与检索

- `POST /v1/lifelog/enqueue_image`
- `POST /v1/lifelog/query`
- `GET /v1/lifelog/timeline`

`enqueue_image` 最小请求体：

```json
{
  "session_id": "session-001",
  "image_base64": "<base64>"
}
```

`query` 最小请求体：

```json
{
  "query": "前方是否有台阶",
  "session_id": "session-001",
  "top_k": 5
}
```

## 2. 安全相关

- `GET /v1/lifelog/safety`
- `GET /v1/lifelog/safety/stats`

可按 `session_id/risk_level/start_ts/end_ts` 过滤。

## 3. 思维轨迹（可选）

- `POST /v1/lifelog/thought_trace`
- `GET /v1/lifelog/thought_trace`
- `GET /v1/lifelog/thought_trace/replay`

写入最小请求体：

```json
{
  "trace_id": "trace-001",
  "stage": "reasoning",
  "payload": {"note": "..."}
}
```

## 4. 设备会话

- `GET /v1/lifelog/device_sessions`

适用于按设备查看会话状态与上下文。

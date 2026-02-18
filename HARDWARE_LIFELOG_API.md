# Hardware Lifelog API

This document describes the lifelog endpoints exposed by the hardware control API.

## 1. Start runtime

```bash
nanobot hardware serve --adapter ec600 --logs
```

Default control API address:

```text
http://127.0.0.1:18792
```

## 2. Auth

If `hardware.auth.enabled=true`, requests must include one of:

1. `Authorization: Bearer <token>`
2. `X-Auth-Token: <token>`

## 3. Endpoints

### 3.1 POST `/v1/lifelog/enqueue_image`

Create a lifelog image entry and semantic context.

Request body:

```json
{
  "session_id": "sess-001",
  "image_base64": "aGVsbG8=",
  "question": "前方有什么障碍物",
  "mime": "image/jpeg",
  "metadata": {
    "risk_level": "P2",
    "risk_score": 0.4
  }
}
```

Success response:

```json
{
  "success": true,
  "session_id": "sess-001",
  "image_id": 12,
  "dedup": false,
  "summary": "scene summary...",
  "ts": 1771300000000
}
```

### 3.2 POST `/v1/lifelog/query`

Search semantic lifelog contexts.

Request body:

```json
{
  "session_id": "sess-001",
  "query": "楼梯",
  "top_k": 5
}
```

Success response:

```json
{
  "success": true,
  "query": "楼梯",
  "top_k": 5,
  "hits": [
    {
      "id": "12",
      "text": "scene summary...",
      "metadata": {
        "session_id": "sess-001",
        "ts": 1771300000000,
        "image_id": 12,
        "dedup": false
      },
      "score": 12.0
    }
  ]
}
```

### 3.3 GET `/v1/lifelog/timeline`

Query time-ordered events for one session.

Query parameters:

1. `session_id` (required)
2. `start_ts` (optional)
3. `end_ts` (optional)
4. `event_type` (optional)
5. `risk_level` (optional)
6. `limit` (optional, default 50)
7. `offset` (optional, default 0)

Example:

```text
GET /v1/lifelog/timeline?session_id=sess-001&limit=20&offset=0
```

Success response:

```json
{
  "success": true,
  "session_id": "sess-001",
  "offset": 0,
  "limit": 20,
  "count": 2,
  "items": [
    {
      "id": 34,
      "session_id": "sess-001",
      "event_type": "image_ingested",
      "ts": 1771300000000,
      "payload": {
        "image_id": 12,
        "dedup": false
      },
      "risk_level": "P3",
      "confidence": 0.0
    }
  ]
}
```

### 3.4 GET `/v1/lifelog/safety`

Query safety-policy audit events (`event_type=safety_policy`).

Query parameters:

1. `session_id` (required)
2. `trace_id` (optional)
3. `source` (optional, e.g. `task_update` / `vision_reply`)
4. `risk_level` (optional)
5. `downgraded` (optional, `true/false`)
6. `start_ts` (optional)
7. `end_ts` (optional)
8. `limit` (optional, default 50)
9. `offset` (optional, default 0)

Example:

```text
GET /v1/lifelog/safety?session_id=sess-001&downgraded=true&limit=20&offset=0
```

Success response:

```json
{
  "success": true,
  "session_id": "sess-001",
  "offset": 0,
  "limit": 20,
  "count": 1,
  "items": [
    {
      "id": 40,
      "event_type": "safety_policy",
      "payload": {
        "trace_id": "trace-1",
        "source": "task_update",
        "downgraded": true
      },
      "risk_level": "P1",
      "confidence": 0.6
    }
  ],
  "filters": {
    "trace_id": "",
    "source": "",
    "risk_level": null,
    "downgraded": true,
    "start_ts": null,
    "end_ts": null
  }
}
```

### 3.5 GET `/v1/lifelog/safety/stats`

Aggregate safety-policy audit metrics for one session.

Query parameters:

1. `session_id` (required)
2. `source` (optional)
3. `risk_level` (optional)
4. `start_ts` (optional)
5. `end_ts` (optional)

Example:

```text
GET /v1/lifelog/safety/stats?session_id=sess-001
```

Success response:

```json
{
  "success": true,
  "session_id": "sess-001",
  "summary": {
    "total": 12,
    "downgraded": 4,
    "downgrade_rate": 0.3333
  },
  "by_source": {
    "task_update": 6,
    "agent_reply": 4,
    "message_tool": 2
  },
  "by_risk_level": {
    "P1": 5,
    "P2": 4,
    "P3": 3
  }
}
```

## 4. Smoke test script

Run:

```bash
bash scripts/lifelog_api_smoke.sh
```

Optional env vars:

1. `CONTROL_API_BASE` (default `http://127.0.0.1:18792`)
2. `AUTH_TOKEN` (when auth is enabled)

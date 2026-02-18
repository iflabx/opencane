# Hardware Digital Task API

This document describes the digital task endpoints exposed by the hardware control API.

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

### 3.1 POST `/v1/digital-task/execute`

Create and start an async digital task.

Request body:

```json
{
  "session_id": "sess-001",
  "device_id": "dev-001",
  "goal": "帮我规划从当前位置到最近医院的路线",
  "timeout_seconds": 120,
  "notify": true,
  "speak": true,
  "interrupt_previous": true,
  "steps": [
    {
      "title": "collect context"
    }
  ]
}
```

Notes:

1. `device_id` is optional but recommended for hardware push.
2. `notify=true` enables runtime push of task status to device (command type `task_update`).
3. `speak=true` also sends TTS announcements for status updates.
4. `interrupt_previous=true` cancels previous unfinished task on the same device.

Success response:

```json
{
  "success": true,
  "accepted": true,
  "task": {
    "task_id": "9a8b7c6d5e4f",
    "session_id": "sess-001",
    "goal": "帮我规划从当前位置到最近医院的路线",
    "status": "pending",
    "steps": [],
    "result": {},
    "error": "",
    "created_at": 1771300000000,
    "updated_at": 1771300000000
  }
}
```

### 3.2 GET `/v1/digital-task/{task_id}`

Get one digital task by id.

Example:

```text
GET /v1/digital-task/9a8b7c6d5e4f
```

Success response:

```json
{
  "success": true,
  "task": {
    "task_id": "9a8b7c6d5e4f",
    "session_id": "sess-001",
    "goal": "帮我规划从当前位置到最近医院的路线",
    "status": "success",
    "steps": [],
    "result": {
      "text": "建议路线..."
    },
    "error": "",
    "created_at": 1771300000000,
    "updated_at": 1771300002310
  }
}
```

### 3.3 POST `/v1/digital-task/{task_id}/cancel`

Cancel one task if it is still running.

Request body:

```json
{
  "reason": "manual_cancel"
}
```

Success response:

```json
{
  "success": true,
  "task": {
    "task_id": "9a8b7c6d5e4f",
    "status": "canceled",
    "error": "manual_cancel"
  }
}
```

### 3.4 GET `/v1/digital-task`

List tasks with optional filters.

Query params:

1. `session_id` (optional)
2. `status` (optional)
3. `limit` (optional, default 20)
4. `offset` (optional, default 0)

Example:

```text
GET /v1/digital-task?session_id=sess-001&status=success&limit=20&offset=0
```

Success response:

```json
{
  "success": true,
  "session_id": "sess-001",
  "status": "success",
  "count": 1,
  "items": [
    {
      "task_id": "9a8b7c6d5e4f",
      "status": "success"
    }
  ]
}
```

### 3.5 GET `/v1/digital-task/stats`

Get digital-task runtime stats.

Query params:

1. `session_id` (optional)

Example:

```text
GET /v1/digital-task/stats?session_id=sess-001
```

Success response:

```json
{
  "success": true,
  "stats": {
    "total": 10,
    "success": 8,
    "failed": 1,
    "timeout": 1,
    "success_rate": 0.8,
    "avg_duration_ms": 1530.2,
    "avg_step_count": 4.1
  }
}
```

## 4. Device Push Behavior

When `device_id` + `notify=true` are provided at execute time:

1. Backend pushes `task_update` command on status transitions:
   - `pending`
   - `running`
   - `success` / `failed` / `timeout` / `canceled`
2. If `speak=true`, backend also pushes TTS status messages.
3. Push uses retry with exponential backoff:
   - retries: `digital_task.status_retry_count`
   - base delay: `digital_task.status_retry_backoff_ms`
4. If device is offline, failed push events are stored in SQLite queue and replayed after next `hello`.
5. `task_update.payload.message` and TTS status text both pass safety policy guard before send; policy audit is recorded as `lifelog event_type=safety_policy`.

## 5. Voice Intent Routing

For hardware voice turns, runtime can route “代操作” intents directly into digital-task flow.

Trigger examples:

1. payload contains `intent=digital_task`
2. payload contains `digital_task=true`
3. transcript matches action intent (e.g. `帮我挂号`, `请帮我预约`)

Routed tasks are created with:

1. `notify=true`
2. `speak=true`
3. `interrupt_previous=true`

## 6. Runtime Recovery

On `nanobot hardware serve` startup, unfinished `pending/running` tasks are auto-recovered and resumed.

## 7. Smoke test script

Run:

```bash
bash scripts/digital_task_smoke.sh
```

Optional env vars:

1. `CONTROL_API_BASE` (default `http://127.0.0.1:18792`)
2. `AUTH_TOKEN` (when auth is enabled)
3. `DEVICE_ID` (for real push test to one online device)

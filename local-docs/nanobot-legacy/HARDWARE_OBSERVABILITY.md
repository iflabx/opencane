# Hardware Observability & Alerting

This document describes runtime observability metrics and alert checks for the blindcane backend.

## 1. Runtime endpoint

### 1.1 GET `/v1/runtime/observability`

Returns key SLO-oriented metrics and threshold-based alerts.

Query parameters:

1. `task_failure_rate_max` (optional, default `0.30`)
2. `safety_downgrade_rate_max` (optional, default `0.35`)
3. `device_offline_rate_max` (optional, default `0.30`)

Example:

```text
GET /v1/runtime/observability?task_failure_rate_max=0.2&safety_downgrade_rate_max=0.3&device_offline_rate_max=0.25
```

Success response:

```json
{
  "success": true,
  "healthy": false,
  "ts": 1771300000000,
  "metrics": {
    "task_total": 120,
    "task_failures": 18,
    "task_failure_rate": 0.15,
    "safety_applied": 260,
    "safety_downgraded": 42,
    "safety_downgrade_rate": 0.1615,
    "devices_total": 40,
    "devices_offline": 3,
    "device_offline_rate": 0.075
  },
  "thresholds": {
    "task_failure_rate_max": 0.1,
    "safety_downgrade_rate_max": 0.15,
    "device_offline_rate_max": 0.05
  },
  "alerts": [
    {
      "metric": "task_failure_rate",
      "value": 0.15,
      "threshold": 0.1
    }
  ]
}
```

`healthy=true` means no alert is triggered.

### 1.2 GET `/v1/runtime/observability/history`

Returns time-window trend points aggregated from in-process observability samples.

Query parameters:

1. `window_seconds` (optional, default `1800`)
2. `bucket_seconds` (optional, default `60`)
3. `max_points` (optional, default `240`)
4. `include_raw` (optional, default `false`)

Example:

```text
GET /v1/runtime/observability/history?window_seconds=3600&bucket_seconds=30&max_points=120
```

Response fields:

1. `points`: bucketed trend points (avg/max rates per bucket)
2. `summary.sample_count`: number of raw samples in window
3. `summary.trend.*_delta`: latest minus earliest delta
4. `latest`: latest sample in window

Data source:

1. Preferred: dedicated observability SQLite (`hardware.observabilitySqlitePath`), history survives process restart.
2. Secondary: lifelog SQLite (when lifelog service is enabled).
3. Fallback: in-memory samples of current process lifecycle.

## 2. Alert check script

Use script:

```bash
bash scripts/runtime_observability_check.sh
```

Optional env vars:

1. `CONTROL_API_BASE` (default `http://127.0.0.1:18792`)
2. `AUTH_TOKEN`
3. `OBS_PROFILE` (default `dev`, allowed: `dev/staging/prod`)
4. `TASK_FAILURE_RATE_MAX` (optional override)
5. `SAFETY_DOWNGRADE_RATE_MAX` (optional override)
6. `DEVICE_OFFLINE_RATE_MAX` (optional override)

Default thresholds by profile:

1. `dev`: task `0.50`, safety `0.50`, offline `0.60`
2. `staging`: task `0.30`, safety `0.35`, offline `0.30`
3. `prod`: task `0.20`, safety `0.25`, offline `0.15`

Exit code:

1. `0`: healthy
2. `1`: unhealthy (alerts triggered)
3. `2`: request/response error

## 3. CI integration

CI runs:

```bash
bash scripts/run_control_api_smoke_ci.sh
```

The wrapper starts `scripts/mock_control_api_server.py`, runs smoke scripts, and finally runs observability check.

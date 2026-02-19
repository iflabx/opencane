# SRE Runbook (Blindcane Backend)

This runbook is for operating the nanobot-based blindcane backend in `dev/staging/prod`.

## 1. Scope

This runbook covers:

1. Hardware runtime and control API
2. Digital task execution
3. Lifelog and safety audit pipeline
4. Runtime observability and alert handling

Core endpoints:

1. `GET /v1/runtime/status`
2. `GET /v1/runtime/observability`
3. `GET /v1/runtime/observability/history`
4. `GET /v1/lifelog/safety/stats`
5. `GET /v1/digital-task/stats`

## 2. Environment Profiles

Use profile templates:

1. `CONFIG_PROFILE_DEV.json`
2. `CONFIG_PROFILE_STAGING.json`
3. `CONFIG_PROFILE_PROD.json`

Recommended alert threshold profiles:

1. dev: `OBS_PROFILE=dev`
2. staging: `OBS_PROFILE=staging`
3. prod: `OBS_PROFILE=prod`

## 3. Startup Checklist

1. Validate config

```bash
nanobot config check --strict
```

2. Start runtime

```bash
nanobot hardware serve --adapter ec600 --logs
```

3. Validate control API

```bash
curl -sS http://127.0.0.1:18792/v1/runtime/status
```

4. Validate observability

```bash
OBS_PROFILE=staging bash scripts/runtime_observability_check.sh
```

5. Optional smoke suite

```bash
bash scripts/lifelog_api_smoke.sh
bash scripts/digital_task_smoke.sh
bash scripts/p4_safety_e2e_smoke.sh
```

## 4. Triage Flow

Use this fixed order to reduce blind spots.

1. Runtime health

```bash
curl -sS "$CONTROL_API_BASE/v1/runtime/status"
curl -sS "$CONTROL_API_BASE/v1/runtime/observability"
curl -sS "$CONTROL_API_BASE/v1/runtime/observability/history?window_seconds=3600&bucket_seconds=60&max_points=120"
```

Check `runtime/status.lifelog.vector_index.backend_mode`:
1. `chroma` means persistent vector retrieval is active.
2. `qdrant` means persistent vector retrieval is active on Qdrant backend.
3. `memory` means degraded non-persistent fallback mode.

2. Safety health

```bash
curl -sS "$CONTROL_API_BASE/v1/lifelog/safety/stats?session_id=<SESSION_ID>"
```

3. Task health

```bash
curl -sS "$CONTROL_API_BASE/v1/digital-task/stats?session_id=<SESSION_ID>"
curl -sS "$CONTROL_API_BASE/v1/digital-task?session_id=<SESSION_ID>&limit=20&offset=0"
```

4. Device/session health

```bash
curl -sS "$CONTROL_API_BASE/v1/device/<DEVICE_ID>/status"
```

## 5. Incident Playbooks

### 5.1 High task failure rate

Symptom:

1. `task_failure_rate` exceeds threshold in `/v1/runtime/observability`

Actions:

1. Check `digital-task/stats` and inspect latest failed tasks.
2. Reduce load by lowering `digitalTask.maxConcurrentTasks`.
3. Increase `digitalTask.defaultTimeoutSeconds` if upstream calls are timing out.
4. If recent deployment caused regression, rollback to previous release.

### 5.2 High safety downgrade rate

Symptom:

1. `safety_downgrade_rate` exceeds threshold

Actions:

1. Query recent `safety` events by source:
   `GET /v1/lifelog/safety?session_id=<SESSION_ID>&limit=100`
2. Use `GET /v1/lifelog/safety/stats` to locate top `source/reason/rule_id`.
3. Adjust safety thresholds conservatively:
   `safety.lowConfidenceThreshold`
   `safety.directionalConfidenceThreshold`
4. If downgrade is from model instability, switch model or reduce generation temperature.

### 5.3 High device offline rate

Symptom:

1. `device_offline_rate` exceeds threshold

Actions:

1. Verify broker connectivity and topic configuration.
2. Check heartbeat settings:
   `hardware.heartbeatSeconds`
   `hardware.mqtt.keepaliveSeconds`
   `hardware.mqtt.heartbeatIntervalSeconds`
3. Validate cellular profile and reconnect range:
   `hardware.networkProfile`
   `hardware.mqtt.reconnectMinSeconds`
   `hardware.mqtt.reconnectMaxSeconds`

### 5.4 No observability history trend

Symptom:

1. `/v1/runtime/observability/history` has empty `points`

Actions:

1. Trigger `/v1/runtime/observability` at least once.
2. Confirm `hardware.observabilitySqlitePath` is writable.
3. If observability sqlite is unavailable, confirm lifelog is enabled as secondary persistence.
4. If both persist layers are unavailable, history only uses in-memory fallback for current process lifecycle.

## 6. Rollback Procedure

1. Stop current service.
2. Deploy previous release artifact.
3. Use previous known-good profile template.
4. Start service and rerun:

```bash
bash scripts/runtime_observability_check.sh
```

5. Verify critical APIs:

1. `/v1/runtime/status`
2. `/v1/runtime/observability`
3. `/v1/lifelog/safety/stats`
4. `/v1/digital-task/stats`

## 7. Post-Incident Checklist

1. Record incident timeline and impacted sessions/devices.
2. Capture before/after metrics from observability and safety stats.
3. Add regression test or smoke case for the root cause.
4. Update profile thresholds or runbook steps if needed.

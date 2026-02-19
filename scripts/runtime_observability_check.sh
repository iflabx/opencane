#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_BASE="${CONTROL_API_BASE:-http://127.0.0.1:18792}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
OBS_PROFILE="${OBS_PROFILE:-dev}"

case "${OBS_PROFILE}" in
  dev)
    _task_failure_default="0.50"
    _safety_downgrade_default="0.50"
    _device_offline_default="0.60"
    ;;
  staging)
    _task_failure_default="0.30"
    _safety_downgrade_default="0.35"
    _device_offline_default="0.30"
    ;;
  prod)
    _task_failure_default="0.20"
    _safety_downgrade_default="0.25"
    _device_offline_default="0.15"
    ;;
  *)
    echo "invalid OBS_PROFILE=${OBS_PROFILE}, expected one of: dev, staging, prod" >&2
    exit 2
    ;;
esac

TASK_FAILURE_RATE_MAX="${TASK_FAILURE_RATE_MAX:-${_task_failure_default}}"
SAFETY_DOWNGRADE_RATE_MAX="${SAFETY_DOWNGRADE_RATE_MAX:-${_safety_downgrade_default}}"
DEVICE_OFFLINE_RATE_MAX="${DEVICE_OFFLINE_RATE_MAX:-${_device_offline_default}}"

echo "control api: ${CONTROL_API_BASE}"
echo "profile: ${OBS_PROFILE}"
echo "thresholds: task_failure<=${TASK_FAILURE_RATE_MAX}, safety_downgrade<=${SAFETY_DOWNGRADE_RATE_MAX}, device_offline<=${DEVICE_OFFLINE_RATE_MAX}"

curl_opts=(
  -sS
  --connect-timeout 5
  --max-time 20
)

if [[ -n "${AUTH_TOKEN}" ]]; then
  curl_opts+=(-H "Authorization: Bearer ${AUTH_TOKEN}")
fi

url="${CONTROL_API_BASE}/v1/runtime/observability?task_failure_rate_max=${TASK_FAILURE_RATE_MAX}&safety_downgrade_rate_max=${SAFETY_DOWNGRADE_RATE_MAX}&device_offline_rate_max=${DEVICE_OFFLINE_RATE_MAX}"
resp="$(curl "${curl_opts[@]}" "${url}")"
echo "${resp}"

RESP_JSON="${resp}" python3 - <<'PY'
import json
import os
import sys

try:
    data = json.loads(os.environ.get("RESP_JSON", "{}"))
except Exception:
    print("invalid observability response json", file=sys.stderr)
    raise SystemExit(2)

if not bool(data.get("success")):
    print(f"observability request failed: {data}", file=sys.stderr)
    raise SystemExit(2)

if not bool(data.get("healthy")):
    print("observability unhealthy:", file=sys.stderr)
    for alert in data.get("alerts", []):
        print(f"  - {alert}", file=sys.stderr)
    raise SystemExit(1)

metrics = data.get("metrics", {})
print(
    "observability healthy "
    f"task_failure_rate={metrics.get('task_failure_rate')} "
    f"safety_downgrade_rate={metrics.get('safety_downgrade_rate')} "
    f"device_offline_rate={metrics.get('device_offline_rate')}"
)
PY

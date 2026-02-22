#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_HOST="${CONTROL_API_HOST:-127.0.0.1}"
CONTROL_API_PORT="${CONTROL_API_PORT:-18792}"
CONTROL_API_BASE="http://${CONTROL_API_HOST}:${CONTROL_API_PORT}"
SERVER_LOG="${SERVER_LOG:-/tmp/opencane_mock_control_api.log}"

echo "starting mock control api server at ${CONTROL_API_BASE}"
python3 scripts/mock_control_api_server.py \
  --host "${CONTROL_API_HOST}" \
  --port "${CONTROL_API_PORT}" \
  >"${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for i in $(seq 1 30); do
  if curl -fsS "${CONTROL_API_BASE}/v1/runtime/status" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ "${i}" == "30" ]]; then
    echo "mock control api start timeout, logs:"
    cat "${SERVER_LOG}" || true
    exit 1
  fi
done

echo "mock control api is ready"

CONTROL_API_BASE="${CONTROL_API_BASE}" \
  SESSION_ID="ci-lifelog-$(date +%s)" \
  bash scripts/lifelog_api_smoke.sh

CONTROL_API_BASE="${CONTROL_API_BASE}" \
  SESSION_ID="ci-task-$(date +%s)" \
  DEVICE_ID="ci-device-1" \
  bash scripts/digital_task_smoke.sh

CONTROL_API_BASE="${CONTROL_API_BASE}" \
  SESSION_ID="ci-safety-$(date +%s)" \
  DEVICE_ID="ci-device-2" \
  bash scripts/p4_safety_e2e_smoke.sh

CONTROL_API_BASE="${CONTROL_API_BASE}" \
  TASK_FAILURE_RATE_MAX="1.0" \
  SAFETY_DOWNGRADE_RATE_MAX="1.0" \
  DEVICE_OFFLINE_RATE_MAX="1.0" \
  bash scripts/runtime_observability_check.sh

echo "== observability history =="
curl -fsS "${CONTROL_API_BASE}/v1/runtime/observability/history?window_seconds=3600&bucket_seconds=30&max_points=120"
echo

echo "control api smoke ci done"

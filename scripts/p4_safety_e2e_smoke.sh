#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_BASE="${CONTROL_API_BASE:-http://127.0.0.1:18792}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
DEVICE_ID="${DEVICE_ID:-dev-safety-smoke}"
SESSION_ID="${SESSION_ID:-sess-safety-$(date +%s)}"
GOAL="${GOAL:-帮我预约明天下午门诊}"

echo "control api: ${CONTROL_API_BASE}"
echo "device id:   ${DEVICE_ID}"
echo "session id:  ${SESSION_ID}"

curl_opts=(
  -sS
  --connect-timeout 5
  --max-time 30
)

if [[ -n "${AUTH_TOKEN}" ]]; then
  curl_opts+=(-H "Authorization: Bearer ${AUTH_TOKEN}")
fi

now_ms() {
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

post_json() {
  local url="$1"
  local payload="$2"
  curl "${curl_opts[@]}" \
    -X POST "${url}" \
    -H "Content-Type: application/json" \
    -d "${payload}"
}

get_json() {
  local url="$1"
  curl "${curl_opts[@]}" "${url}"
}

echo
echo "== inject hello event =="
hello_payload="$(cat <<JSON
{
  "version": "0.1",
  "msg_id": "smoke-hello-${SESSION_ID}",
  "device_id": "${DEVICE_ID}",
  "session_id": "${SESSION_ID}",
  "seq": 1,
  "ts": $(now_ms),
  "type": "hello",
  "payload": {
    "trace_id": "smoke-trace-${SESSION_ID}",
    "capabilities": {
      "network": "cellular",
      "camera": true
    }
  }
}
JSON
)"
post_json "${CONTROL_API_BASE}/v1/device/event" "${hello_payload}"
echo

echo
echo "== execute digital task =="
execute_payload="$(cat <<JSON
{
  "session_id": "${SESSION_ID}",
  "device_id": "${DEVICE_ID}",
  "goal": "${GOAL}",
  "notify": true,
  "speak": true,
  "interrupt_previous": true
}
JSON
)"
execute_resp="$(post_json "${CONTROL_API_BASE}/v1/digital-task/execute" "${execute_payload}")"
echo "${execute_resp}"
task_id="$(EXECUTE_RESP="${execute_resp}" python3 - <<'PY'
import json
import os

try:
    data = json.loads(os.environ.get("EXECUTE_RESP", "{}"))
except Exception:
    print("")
    raise SystemExit(0)

task = data.get("task")
if isinstance(task, dict):
    print(task.get("task_id", ""))
else:
    print("")
PY
)"
if [[ -z "${task_id}" ]]; then
  echo
  echo "task_id not found in execute response; stop."
  exit 1
fi

echo
echo "task id: ${task_id}"
echo "waiting 2s for task updates..."
sleep 2

echo
echo "== digital task status =="
get_json "${CONTROL_API_BASE}/v1/digital-task/${task_id}"
echo

echo
echo "== safety audit query =="
get_json "${CONTROL_API_BASE}/v1/lifelog/safety?session_id=${SESSION_ID}&limit=20"
echo

echo
echo "p4 safety e2e smoke done"

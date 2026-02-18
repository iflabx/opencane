#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_BASE="${CONTROL_API_BASE:-http://127.0.0.1:18792}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
SESSION_ID="${SESSION_ID:-sess-$(date +%s)}"
DEVICE_ID="${DEVICE_ID:-}"

echo "control api: ${CONTROL_API_BASE}"
echo "session id:  ${SESSION_ID}"
if [[ -n "${DEVICE_ID}" ]]; then
  echo "device id:   ${DEVICE_ID}"
fi

curl_opts=(
  -sS
  --connect-timeout 5
  --max-time 30
)

if [[ -n "${AUTH_TOKEN}" ]]; then
  curl_opts+=(-H "Authorization: Bearer ${AUTH_TOKEN}")
fi

echo
echo "== execute =="
execute_resp="$(
  if [[ -n "${DEVICE_ID}" ]]; then
    device_id_json="\"device_id\": \"${DEVICE_ID}\","
  else
    device_id_json=""
  fi
  curl "${curl_opts[@]}" \
    -X POST "${CONTROL_API_BASE}/v1/digital-task/execute" \
    -H "Content-Type: application/json" \
    -d "{
      \"session_id\": \"${SESSION_ID}\",
      ${device_id_json}
      \"goal\": \"请给我一个今天出行提醒和避障建议\",
      \"timeout_seconds\": 120,
      \"notify\": true,
      \"speak\": true
    }"
)"
echo "${execute_resp}"

task_id="$(printf '%s' "${execute_resp}" | sed -n 's/.*"task_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [[ -z "${task_id}" ]]; then
  echo "failed: cannot parse task_id from execute response" >&2
  exit 1
fi

echo
echo "task id: ${task_id}"
echo "== get task =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/digital-task/${task_id}"
echo

echo
echo "== list tasks =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/digital-task?session_id=${SESSION_ID}&limit=20&offset=0"
echo

echo
echo "== stats =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/digital-task/stats?session_id=${SESSION_ID}"
echo

echo
echo "== cancel task =="
curl "${curl_opts[@]}" \
  -X POST "${CONTROL_API_BASE}/v1/digital-task/${task_id}/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "smoke_test_cancel"
  }'
echo

echo
echo "smoke done"

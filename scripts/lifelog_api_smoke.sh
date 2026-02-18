#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_BASE="${CONTROL_API_BASE:-http://127.0.0.1:18792}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
SESSION_ID="${SESSION_ID:-sess-$(date +%s)}"

echo "control api: ${CONTROL_API_BASE}"
echo "session id:  ${SESSION_ID}"

curl_opts=(
  -sS
  --connect-timeout 5
  --max-time 30
)

if [[ -n "${AUTH_TOKEN}" ]]; then
  curl_opts+=(-H "Authorization: Bearer ${AUTH_TOKEN}")
fi

image_b64="$(printf 'nanobot-lifelog-smoke-image' | base64 | tr -d '\n')"

echo
echo "== enqueue_image =="
curl "${curl_opts[@]}" \
  -X POST "${CONTROL_API_BASE}/v1/lifelog/enqueue_image" \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"${SESSION_ID}\",
    \"image_base64\": \"${image_b64}\",
    \"question\": \"前方有什么障碍物\",
    \"mime\": \"image/jpeg\"
  }"
echo

echo
echo "== query =="
curl "${curl_opts[@]}" \
  -X POST "${CONTROL_API_BASE}/v1/lifelog/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"${SESSION_ID}\",
    \"query\": \"障碍物\",
    \"top_k\": 5
  }"
echo

echo
echo "== timeline =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/lifelog/timeline?session_id=${SESSION_ID}&limit=20&offset=0"
echo

echo
echo "== safety =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/lifelog/safety?session_id=${SESSION_ID}&limit=20&offset=0"
echo

echo
echo "== safety stats =="
curl "${curl_opts[@]}" \
  "${CONTROL_API_BASE}/v1/lifelog/safety/stats?session_id=${SESSION_ID}"
echo

echo
echo "smoke done"

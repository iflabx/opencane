#!/usr/bin/env bash
set -euo pipefail

CONTROL_API_BASE="${CONTROL_API_BASE:-http://127.0.0.1:18792}"
AUTH_TOKEN="${AUTH_TOKEN:-}"

echo "control api: ${CONTROL_API_BASE}"

auth_args=()
if [[ -n "${AUTH_TOKEN}" ]]; then
  auth_args+=(--auth-token "${AUTH_TOKEN}")
fi

python3 scripts/replay_hardware_events.py \
  --base-url "${CONTROL_API_BASE}" \
  --scenario scripts/replay_cases/voice_turn_nominal.json \
  --expect-voice-turn-min 1 \
  "${auth_args[@]}"

python3 scripts/replay_hardware_events.py \
  --base-url "${CONTROL_API_BASE}" \
  --scenario scripts/replay_cases/duplicate_out_of_order.json \
  --expect-duplicate-events-min 1 \
  "${auth_args[@]}"

echo "replay contract smoke done"

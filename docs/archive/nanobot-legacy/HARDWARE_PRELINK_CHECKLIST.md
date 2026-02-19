# Hardware Pre-Link Checklist (Soft/Simulation)

This checklist is for pre-hardware integration gates. It ensures backend, protocol mapping, and replay contracts are stable before real device bring-up.

## 1. Protocol and mapping readiness

1. Canonical contract is confirmed:
- `EDGE_ADAPTER_SDK_PROTOCOL_V0.md`

2. Chip/protocol mapping template is filled (at least draft):
- `EC600_PROTOCOL_MAPPING_TEMPLATE.md`

3. Required control API docs are aligned with runtime:
- `HARDWARE_DIGITAL_TASK_API.md`
- `HARDWARE_LIFELOG_API.md`
- `HARDWARE_OBSERVABILITY.md`

## 2. No-hardware smoke gate

Run:

```bash
bash scripts/run_control_api_smoke_ci.sh
```

Pass criteria:
- `lifelog_api_smoke.sh` passes
- `digital_task_smoke.sh` passes
- `p4_safety_e2e_smoke.sh` passes
- `runtime_observability_check.sh` passes

## 3. Event replay contract gate

Start runtime (mock adapter):

```bash
nanobot hardware serve --adapter mock --logs
```

Replay nominal voice turn:

```bash
python3 scripts/replay_hardware_events.py \
  --base-url http://127.0.0.1:18792 \
  --scenario scripts/replay_cases/voice_turn_nominal.json \
  --expect-voice-turn-min 1
```

Replay duplicate/out-of-order anomaly:

```bash
python3 scripts/replay_hardware_events.py \
  --base-url http://127.0.0.1:18792 \
  --scenario scripts/replay_cases/duplicate_out_of_order.json \
  --expect-duplicate-events-min 1
```

Pass criteria:
- replay tool exits with code `0`
- runtime status exposes expected metric changes

## 4. Regression gate

Run key suites:

```bash
pytest -x \
  tests/test_hardware_event_replay_contract.py \
  tests/test_hardware_runtime.py \
  tests/test_hardware_control_digital_task_api.py \
  tests/test_hardware_control_lifelog_api.py \
  tests/test_ec600_mqtt_adapter.py
```

Optional full gate:

```bash
pytest -x
```

## 5. Handover inputs required from hardware team

1. Southbound transport details (MQTT/WS/HTTP, topic/path naming, QoS)
2. Authentication fields and key rotation policy
3. Audio format details (codec/sample-rate/frame size/chunk interval)
4. Image transport constraints (max bytes, retries, timeout)
5. Device state/error code table and reconnect behavior
6. OTA capability flags and rollback expectations

Without these, only soft/simulation integration can be completed.

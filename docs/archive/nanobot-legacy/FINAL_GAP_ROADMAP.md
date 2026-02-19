# Nanobot Blindcane Gap Matrix and Roadmap (2026-02-18)

## 1. Current Overall Status

Non-hardware baseline is closed for the current architecture scope:

1. P0 core chain complete:
   - multimodal vision structured schema
   - async ingest queue and backpressure
   - unified memory retrieval integration
   - device session persistence
2. Previously identified 8 residual P0/P1 gaps are implemented:
   - session seq persistence precision
   - runtime stop session close persistence
   - device auth/binding lifecycle
   - control-plane cached/fallback client skeleton
   - realtime speech engineering (`stt_partial`, barge-in interrupt, chunk reorder)
   - tool domain manager + recursion guard
   - optional Qdrant backend with fallback
   - docs/runbook alignment
3. Remaining blockers are hardware joint-debug items only.
4. Latest regression verification: `python3 -m ruff check .` and `python3 -m pytest -x` passed (`214 passed, 1 warning`).

## 2. Requirement Matrix (Updated)

| Requirement Area | Current Status | Notes |
|---|---|---|
| Hardware runtime + canonical protocol | Done (MVP) | Runtime, adapters, control API, session lifecycle in place. |
| Voice conversation | Done (MVP+) | STT/TTS chain, partial transcript, interruption, safety audit in place. |
| Multimodal image recognition | Done (MVP+) | Structured context ingest, retrieval, timeline filters in place. |
| Long-context memory | Done (MVP) | Unified file memory + lifelog retrieval integrated. |
| Digital task (OpenClaw-like) | Done (MVP) | MCP-first + fallback + persistence/recovery implemented. |
| Safety policy and audit | Done (MVP) | Runtime + agent safety guards and queryable audit stats implemented. |
| Device auth/binding lifecycle | Done (MVP) | register/bind/activate/revoke + runtime validation implemented. |
| Hardware protocol freeze + field tuning | Blocked by hardware | Requires real firmware/network validation. |

## 3. Borrowing Matrix (MineContext) - Updated

| Borrowing Item | Status | Notes |
|---|---|---|
| Async image queue + backpressure | Done | Bounded queue, worker pool, overflow policy, queue metrics. |
| Near-duplicate strategy | Done | dHash-based near-duplicate flow with timeline persistence. |
| Structured VLM schema output | Done | `objects/ocr/risk_hints/actionable_summary` persisted and queryable. |
| Semantic index chain | Done | Context semantic index and retrieval are integrated. |
| Dual vector backend (Chroma/Qdrant) | Done (optional) | `vector_backend` supports `chroma|qdrant` with fallback mode. |
| Retention lifecycle | Done | Image asset cleanup and deleted markers implemented. |
| Deep observability dimensions | Done (MVP) | runtime/queue/task/safety metrics + history API in place. |
| Thought-trace persistence/replay | Done (P2) | `thought_traces` persistence + query/replay API implemented. |

## 4. Borrowing Matrix (xiaozhi-esp32-server) - Updated

| Borrowing Item | Status | Notes |
|---|---|---|
| Control/data plane separation | Done (MVP) | `control_plane` runtime config + device policy fetch with cache/fallback and runtime refresh. |
| Device auth + binding activation | Done | Lifecycle APIs + runtime gate landed. |
| Per-connection state machine | Done | Session state and seq dedup/persistence in place. |
| Realtime speech engineering | Done (MVP+) | partial transcript, barge-in stop, chunk reorder support implemented. |
| Unified tool orchestration (multi-domain) | Done (MVP) | domain manager + guardrail + spawn recursion limit implemented. |
| Independent vision entry | Done | Vision service + API available. |
| Layered long memory | Done (MVP) | Agent retrieval path unified with lifelog provider. |
| Dynamic device context injection | Done (MVP+) | Device session/telemetry/policy context injected into agent prompt path. |
| OTA/device ops/audit replay | Done (P2) | Device ops dispatch/query/ack plus thought-trace replay API delivered. |

## 5. Completed Milestones

### P0 Milestone

1. Structured vision schema.
2. Async ingest queue + backpressure.
3. Unified memory provider integration.
4. Device session persistence table.

### P1 Milestone

1. Tool domain manager + recursion guard.
2. Control-plane runtime/device policy integration.
3. Enhanced observability APIs and persistence.
4. Dynamic device context injection (MVP level).

### P2 Milestone

1. Device binding/activation lifecycle: done (MVP).
2. Optional Qdrant backend: done.
3. OTA / device ops control API: done (dispatch/query/ack).
4. Thought-trace persistence and replay: done (storage + API + replay summary).

## 6. Hardware-Blocked Items (Deferred)

Blocked until device-side prerequisites are available:

1. HW-07 topic/payload freeze with real firmware.
2. HW-08 wire-level audio frame/header validation.
3. HW-09 cellular heartbeat/timeout tuning by field metrics.

Prerequisites:

1. Broker connectivity details.
2. EC600 protocol samples or packet captures.
3. Minimal device-side integration path for `hello/listen/audio/listen_stop`.

## 7. Next Execution Order

1. Hardware joint-debug recovery (HW-07/08/09).
2. Protocol freeze and wire-level validation with real firmware.
3. Cellular heartbeat/timeout tuning based on field data.

## 8. Exit Criteria

Functionally complete except hardware integration:

1. P0/P1 and non-hardware P2 items above are complete with tests.
2. Regression remains green.
3. Hardware blocked items are isolated and documented.

Production-ready blindcane backend:

1. HW-07/08/09 verified on real devices and network.
2. OTA/device ops and trace replay capabilities delivered.

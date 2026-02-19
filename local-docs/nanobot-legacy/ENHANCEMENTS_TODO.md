# Enhancements TODO (Deferred)

## Scope
These items are non-blocking for current non-hardware delivery. They are intentionally deferred after completing the mandatory baseline (control API security, voice observability metrics, and modular extraction).

## P2 - Productization and Scale
1. OTA release pipeline
- Build full OTA package lifecycle: build/sign/publish, staged rollout, canary, rollback, and post-upgrade verification.
- Add OTA release metadata service and device-side compatibility gating.

2. Distributed ingest and storage scale-out
- Replace single-node queue/path assumptions with pluggable distributed queue (e.g. Redis/Kafka) and object storage for media assets.
- Add backpressure and per-tenant quotas across runtime/lifelog ingestion.

3. Security hardening beyond baseline
- Add mTLS between hardware edge gateways and control backend.
- Add RBAC for control API/operator operations and key rotation workflow.
- Add audit log signing + tamper-evidence chain for high-risk control operations.

4. Caregiver/emergency notification productization
- Move emergency events to an explicit policy engine with escalation graph (SMS/phone/app).
- Add retry/ack SLA tracking and incident timeline export.

## P3 - Architecture Evolution
5. Continue decomposition of oversized modules
- Further split `nanobot/api/hardware_server.py` into route modules (device ops, lifelog, digital-task, observability, auth/security middlewares).
- Introduce explicit request context + middleware chain to reduce per-handler coupling.

6. Protocol compatibility test matrix
- Add contract tests for multiple edge transport adapters (MQTT/WebSocket/HTTP bridge) with unified golden-cases.
- Add compatibility profiles for different modem/chip stacks (EC600 and future variants).

## P4 - Operations
7. SRE dashboard and alerts
- Turn current runtime observability metrics into dashboard templates and alert rules.
- Add SLOs for voice turn latency/failure, control API health, and ingest saturation.

8. Chaos and reliability drills
- Add automated failure-injection scenarios for broker disconnect, delayed STT/VLM, and storage degradation.
- Persist incident playbooks linked with runbook automation.

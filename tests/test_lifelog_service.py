import asyncio
import base64

import pytest

from nanobot.api.lifelog_service import LifelogService
from nanobot.config.schema import Config


class _DummyAnalyzer:
    async def analyze(self, *, question: str, image: bytes, mime: str):  # type: ignore[no-untyped-def]
        del image, mime
        return {"success": True, "result": f"analyzed:{question}"}


class _StructuredAnalyzer:
    async def analyze(self, *, question: str, image: bytes, mime: str):  # type: ignore[no-untyped-def]
        del question, image, mime
        return {
            "summary": "路口前方有台阶和出口标识",
            "objects": [{"label": "台阶"}, {"label": "路口"}],
            "ocr": [{"text": "出口"}],
            "risk_hints": ["台阶较陡"],
            "actionable_summary": "放慢速度并确认台阶高度。",
            "risk_level": "P1",
            "risk_score": 0.7,
            "confidence": 0.9,
        }


class _SlowAnalyzer:
    async def analyze(self, *, question: str, image: bytes, mime: str):  # type: ignore[no-untyped-def]
        del question, image, mime
        await asyncio.sleep(0.2)
        return {"success": True, "result": "slow-analysis"}


@pytest.mark.asyncio
async def test_lifelog_service_enqueue_query_timeline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    config.lifelog.default_top_k = 3

    service = LifelogService.from_config(config, analyzer=_DummyAnalyzer())
    try:
        payload = base64.b64encode(b"image-1").decode("ascii")
        enqueue = await service.enqueue_image(
            {
                "session_id": "sess-a",
                "image_base64": payload,
                "question": "楼梯在哪里",
            }
        )
        assert enqueue["success"] is True
        assert enqueue["session_id"] == "sess-a"

        query = await service.query({"session_id": "sess-a", "query": "楼梯"})
        assert query["success"] is True
        assert query["hits"]

        timeline = await service.timeline_query({"session_id": "sess-a", "limit": 10})
        assert timeline["success"] is True
        assert timeline["count"] >= 1
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_ingest_queue_backpressure_and_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    config.lifelog.ingest_queue_max_size = 1
    config.lifelog.ingest_workers = 1
    config.lifelog.ingest_overflow_policy = "reject"

    service = LifelogService.from_config(config, analyzer=_SlowAnalyzer())
    try:
        payload = base64.b64encode(b"image-backpressure").decode("ascii")

        async def _enqueue(idx: int) -> dict:
            return await service.enqueue_image(
                {
                    "session_id": f"sess-queue-{idx}",
                    "image_base64": payload,
                    "question": f"q-{idx}",
                }
            )

        results = await asyncio.gather(_enqueue(1), _enqueue(2), _enqueue(3))
        rejected = [item for item in results if not bool(item.get("success")) and item.get("error_code") == "queue_full"]
        assert len(rejected) >= 1

        status = service.status_snapshot()
        queue = status.get("ingest_queue", {})
        assert int(queue.get("max_size", 0)) == 1
        assert int(queue.get("rejected_total", 0)) >= 1
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_query_and_timeline_support_structured_filters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")

    service = LifelogService.from_config(config, analyzer=_StructuredAnalyzer())
    try:
        payload = base64.b64encode(b"image-structured").decode("ascii")
        enqueue = await service.enqueue_image(
            {
                "session_id": "sess-structured",
                "image_base64": payload,
                "question": "前方风险",
            }
        )
        assert enqueue["success"] is True
        assert enqueue["structured_context"]["objects"][0]["label"] == "台阶"

        query = await service.query(
            {
                "session_id": "sess-structured",
                "query": "路口",
                "has_objects": True,
                "object_contains": "台阶",
                "include_context": True,
            }
        )
        assert query["success"] is True
        assert len(query["hits"]) == 1
        assert query["hits"][0]["structured_context"]["risk_hints"] == ["台阶较陡"]

        timeline = await service.timeline_query(
            {
                "session_id": "sess-structured",
                "event_type": "image_ingested",
                "has_ocr": True,
                "ocr_contains": "出口",
            }
        )
        assert timeline["success"] is True
        assert timeline["count"] == 1
        payload_map = timeline["items"][0]["payload"]["structured_context"]
        assert payload_map["actionable_summary"].startswith("放慢速度")
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_validates_required_fields(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        enqueue = await service.enqueue_image({"session_id": "sess-a"})
        assert enqueue["success"] is False

        query = await service.query({})
        assert query["success"] is False

        timeline = await service.timeline_query({})
        assert timeline["success"] is False
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_safety_query_and_timeline_filters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        service.record_runtime_event(
            session_id="sess-safe",
            event_type="safety_policy",
            payload={
                "trace_id": "trace-safe-1",
                "source": "task_update",
                "downgraded": True,
            },
            risk_level="P1",
            confidence=0.4,
            ts=1000,
        )
        service.record_runtime_event(
            session_id="sess-safe",
            event_type="voice_turn",
            payload={"trace_id": "trace-voice"},
            risk_level="P3",
            confidence=0.9,
            ts=2000,
        )
        service.record_runtime_event(
            session_id="sess-safe",
            event_type="safety_policy",
            payload={
                "trace_id": "trace-safe-2",
                "source": "agent_reply",
                "downgraded": False,
                "reason": "ok",
                "rule_ids": ["output_truncated"],
                "policy_version": "v1.1",
            },
            risk_level="P3",
            confidence=0.8,
            ts=3000,
        )

        safety = await service.safety_query(
            {
                "session_id": "sess-safe",
                "trace_id": "trace-safe-1",
                "downgraded": True,
                "limit": 10,
            }
        )
        assert safety["success"] is True
        assert safety["count"] == 1
        assert safety["items"][0]["event_type"] == "safety_policy"
        assert safety["offset"] == 0

        timeline = await service.timeline_query(
            {
                "session_id": "sess-safe",
                "event_type": "safety_policy",
                "risk_level": "P1",
                "limit": 10,
            }
        )
        assert timeline["success"] is True
        assert timeline["count"] == 1
        assert timeline["items"][0]["event_type"] == "safety_policy"

        timeline_page2 = await service.timeline_query(
            {
                "session_id": "sess-safe",
                "event_type": "safety_policy",
                "limit": 1,
                "offset": 1,
            }
        )
        assert timeline_page2["success"] is True
        assert timeline_page2["count"] == 1
        assert timeline_page2["offset"] == 1

        safety_page2 = await service.safety_query(
            {
                "session_id": "sess-safe",
                "limit": 1,
                "offset": 1,
            }
        )
        assert safety_page2["success"] is True
        assert safety_page2["count"] == 1
        assert safety_page2["offset"] == 1

        stats = await service.safety_stats({"session_id": "sess-safe"})
        assert stats["success"] is True
        assert stats["summary"]["total"] == 2
        assert stats["summary"]["downgraded"] == 1
        assert "task_update" in stats["by_source"]
        assert "agent_reply" in stats["by_source"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_thought_trace_append_query_and_replay(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog-thought.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        missing_stage = await service.thought_trace_append({"trace_id": "trace-a"})
        assert missing_stage["success"] is False

        first = await service.thought_trace_append(
            {
                "trace_id": "trace-a",
                "session_id": "sess-a",
                "source": "runtime:voice_turn",
                "stage": "voice_turn",
                "payload": {"transcript": "你好"},
                "ts": 1000,
            }
        )
        assert first["success"] is True

        second = await service.thought_trace_append(
            {
                "trace_id": "trace-a",
                "session_id": "sess-a",
                "source": "runtime:safety_policy",
                "stage": "safety_policy",
                "payload": {"downgraded": True},
                "ts": 1200,
            }
        )
        assert second["success"] is True

        query = await service.thought_trace_query(
            {
                "trace_id": "trace-a",
                "session_id": "sess-a",
                "order": "asc",
                "limit": 10,
                "offset": 0,
            }
        )
        assert query["success"] is True
        assert query["count"] == 2
        assert query["items"][0]["stage"] == "voice_turn"
        assert query["items"][1]["stage"] == "safety_policy"

        replay = await service.thought_trace_replay({"trace_id": "trace-a"})
        assert replay["success"] is True
        assert replay["summary"]["count"] == 2
        assert replay["summary"]["duration_ms"] == 200
        assert replay["steps"][0]["stage"] == "voice_turn"
        assert replay["steps"][1]["payload"]["downgraded"] is True
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_record_runtime_event_auto_appends_thought_trace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog-runtime-trace.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        service.record_runtime_event(
            session_id="sess-runtime",
            event_type="safety_policy",
            payload={"trace_id": "trace-runtime-1", "downgraded": True, "source": "task_update"},
            risk_level="P1",
            confidence=0.4,
            ts=1500,
        )
        service.record_runtime_event(
            session_id="sess-runtime",
            event_type="voice_turn",
            payload={"text": "no trace"},
            risk_level="P3",
            confidence=0.9,
            ts=1600,
        )

        trace = await service.thought_trace_query({"trace_id": "trace-runtime-1"})
        assert trace["success"] is True
        assert trace["count"] == 1
        item = trace["items"][0]
        assert item["source"] == "runtime:safety_policy"
        assert item["stage"] == "safety_policy"
        assert item["session_id"] == "sess-runtime"
        assert item["payload"]["risk_level"] == "P1"
        assert item["payload"]["payload"]["downgraded"] is True
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_device_sessions_query(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        service.store.upsert_device_session(
            device_id="dev-1",
            session_id="sess-a",
            state="ready",
            created_at_ms=1000,
            last_seen_ms=1100,
            metadata={"firmware": "v1"},
        )
        service.store.close_device_session(
            device_id="dev-1",
            session_id="sess-a",
            reason="heartbeat_timeout",
            closed_at_ms=1200,
        )
        result = await service.device_sessions_query(
            {
                "device_id": "dev-1",
                "state": "closed",
                "limit": 10,
                "offset": 0,
            }
        )
        assert result["success"] is True
        assert result["count"] == 1
        assert result["items"][0]["close_reason"] == "heartbeat_timeout"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_device_binding_lifecycle_and_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        reg = await service.device_register({"device_id": "dev-auth", "device_token": "token-1"})
        assert reg["success"] is True
        assert reg["device"]["status"] == "registered"

        bind = await service.device_bind({"device_id": "dev-auth", "user_id": "user-1"})
        assert bind["success"] is True
        assert bind["device"]["status"] == "bound"

        activate = await service.device_activate({"device_id": "dev-auth"})
        assert activate["success"] is True
        assert activate["device"]["status"] == "activated"

        query = await service.device_binding_query({"device_id": "dev-auth"})
        assert query["success"] is True
        assert query["count"] == 1
        assert query["items"][0]["user_id"] == "user-1"

        ok = service.validate_device_auth(
            device_id="dev-auth",
            device_token="token-1",
            require_activated=True,
            allow_unbound=False,
        )
        assert ok["success"] is True

        bad = service.validate_device_auth(
            device_id="dev-auth",
            device_token="wrong",
            require_activated=True,
            allow_unbound=False,
        )
        assert bad["success"] is False

        revoke = await service.device_revoke({"device_id": "dev-auth", "reason": "manual"})
        assert revoke["success"] is True
        assert revoke["device"]["status"] == "revoked"

        revoked = service.validate_device_auth(
            device_id="dev-auth",
            device_token="token-1",
            require_activated=True,
            allow_unbound=False,
        )
        assert revoked["success"] is False
        assert revoked["reason"] == "device_revoked"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_device_operation_lifecycle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog-ops.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        queued = await service.device_operation_enqueue(
            {
                "device_id": "dev-ops-1",
                "session_id": "sess-ops-1",
                "op_type": "ota_plan",
                "payload": {"version": "1.2.3", "url": "https://example.com/fw.bin"},
            }
        )
        assert queued["success"] is True
        operation = queued.get("operation") or {}
        operation_id = str(operation.get("operation_id") or "")
        assert operation_id
        assert operation.get("status") == "queued"

        sent = await service.device_operation_mark(
            {
                "operation_id": operation_id,
                "status": "sent",
                "result": {"seq": 8},
            }
        )
        assert sent["success"] is True
        assert sent["operation"]["status"] == "sent"

        acked = await service.device_operation_mark(
            {
                "operation_id": operation_id,
                "status": "acked",
                "result": {"device_ack": True},
                "acked_at_ms": 2000,
            }
        )
        assert acked["success"] is True
        assert acked["operation"]["status"] == "acked"
        assert int(acked["operation"]["acked_at_ms"]) == 2000

        query_one = await service.device_operation_query({"operation_id": operation_id})
        assert query_one["success"] is True
        assert query_one["count"] == 1
        assert query_one["items"][0]["status"] == "acked"

        query_list = await service.device_operation_query(
            {"device_id": "dev-ops-1", "status": "acked", "limit": 10, "offset": 0}
        )
        assert query_list["success"] is True
        assert query_list["count"] == 1
        assert query_list["items"][0]["operation_id"] == operation_id
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_telemetry_samples_and_retention_cleanup(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog-telemetry.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    service = LifelogService.from_config(config, analyzer=None)
    try:
        appended = service.append_telemetry_sample(
            {
                "device_id": "dev-tele-1",
                "session_id": "sess-tele-1",
                "schema_version": "opencane.telemetry.v1",
                "sample": {"battery": {"percent": 77}},
                "raw": {"battery": 77},
                "trace_id": "trace-tele-1",
                "ts": 1000,
            }
        )
        assert appended["success"] is True
        assert int(appended["sample_id"]) > 0

        queried = await service.telemetry_samples_query(
            {"device_id": "dev-tele-1", "session_id": "sess-tele-1", "limit": 10, "offset": 0}
        )
        assert queried["success"] is True
        assert queried["count"] == 1
        assert queried["items"][0]["schema_version"] == "opencane.telemetry.v1"

        cleaned = await service.retention_cleanup({"telemetry_samples_days": 1})
        assert cleaned["success"] is True
        assert int(cleaned["deleted"]["telemetry_samples"]) >= 1
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_observability_samples_persist_across_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    sqlite_path = tmp_path / "lifelog-observability.db"
    chroma_dir = tmp_path / "chroma-observability"
    image_dir = tmp_path / "images-observability"
    config.lifelog.sqlite_path = str(sqlite_path)
    config.lifelog.chroma_persist_dir = str(chroma_dir)
    config.lifelog.image_asset_dir = str(image_dir)

    service = LifelogService.from_config(config, analyzer=None)
    try:
        service.record_observability_sample(
            {
                "ts": 1000,
                "healthy": True,
                "metrics": {"task_failure_rate": 0.1},
                "thresholds": {"task_failure_rate_max": 0.3},
            }
        )
        service.record_observability_sample(
            {
                "ts": 2000,
                "healthy": False,
                "metrics": {"task_failure_rate": 0.6},
                "thresholds": {"task_failure_rate_max": 0.3},
            }
        )
        samples = service.list_observability_samples(start_ts=900, end_ts=3000, limit=20)
        assert len(samples) == 2
    finally:
        await service.shutdown()

    service2 = LifelogService.from_config(config, analyzer=None)
    try:
        samples2 = service2.list_observability_samples(start_ts=900, end_ts=3000, limit=20)
        assert len(samples2) == 2
        assert any(bool(item.get("healthy")) for item in samples2)
        assert any(not bool(item.get("healthy")) for item in samples2)
    finally:
        await service2.shutdown()


@pytest.mark.asyncio
async def test_lifelog_service_qdrant_backend_init_failure_falls_back(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class _BrokenQdrant:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("qdrant init failed")

    monkeypatch.setattr("nanobot.api.lifelog_service.QdrantLifelogIndex", _BrokenQdrant)

    config = Config()
    config.lifelog.sqlite_path = str(tmp_path / "lifelog.db")
    config.lifelog.chroma_persist_dir = str(tmp_path / "chroma")
    config.lifelog.image_asset_dir = str(tmp_path / "images")
    config.lifelog.vector_backend = "qdrant"

    service = LifelogService.from_config(config, analyzer=None)
    try:
        status = service.status_snapshot()
        vector = status.get("vector_index", {})
        assert str(vector.get("backend_mode") or "") != "qdrant"
    finally:
        await service.shutdown()

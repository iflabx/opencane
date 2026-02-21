"""Lifelog store facade for vision pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opencane.storage.sqlite_lifelog import SQLiteLifelogStore


class VisionLifelogStore:
    """Facade around SQLite lifelog storage for the multimodal pipeline."""

    def __init__(self, db: SQLiteLifelogStore | str | Path) -> None:
        self.db = db if isinstance(db, SQLiteLifelogStore) else SQLiteLifelogStore(db)

    def close(self) -> None:
        self.db.close()

    def recent_hashes(self, *, session_id: str, limit: int = 50) -> list[str]:
        return self.db.recent_hashes(session_id=session_id, limit=limit)

    def record_image(
        self,
        *,
        session_id: str,
        image_uri: str,
        dhash: str,
        is_dedup: bool,
        ts: int,
    ) -> int:
        return self.db.add_image(
            session_id=session_id,
            image_uri=image_uri,
            dhash=dhash,
            is_dedup=is_dedup,
            ts=ts,
        )

    def record_context(
        self,
        *,
        image_id: int,
        semantic_title: str,
        semantic_summary: str,
        objects: list[dict[str, Any]] | None = None,
        ocr: list[dict[str, Any]] | None = None,
        risk_hints: list[str] | None = None,
        actionable_summary: str = "",
        risk_level: str = "P3",
        risk_score: float = 0.0,
        ts: int,
    ) -> int:
        return self.db.add_context(
            image_id=image_id,
            semantic_title=semantic_title,
            semantic_summary=semantic_summary,
            objects=objects,
            ocr=ocr,
            risk_hints=risk_hints,
            actionable_summary=actionable_summary,
            risk_level=risk_level,
            risk_score=risk_score,
            ts=ts,
        )

    def get_context_by_image_id(self, *, image_id: int) -> dict[str, Any] | None:
        return self.db.get_context_by_image_id(image_id=image_id)

    def get_contexts_by_image_ids(self, *, image_ids: list[int]) -> dict[int, dict[str, Any]]:
        return self.db.get_contexts_by_image_ids(image_ids=image_ids)

    def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        risk_level: str = "P3",
        confidence: float = 0.0,
        ts: int | None = None,
    ) -> int:
        return self.db.add_event(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            risk_level=risk_level,
            confidence=confidence,
            ts=ts,
        )

    def mark_assets_deleted(self, *, image_uris: list[str]) -> int:
        return self.db.mark_image_assets_deleted(image_uris=image_uris)

    def timeline(
        self,
        *,
        session_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        event_type: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.timeline(
            session_id=session_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type=event_type,
            risk_level=risk_level,
            limit=limit,
            offset=offset,
        )

    def upsert_device_session(
        self,
        *,
        device_id: str,
        session_id: str,
        state: str,
        created_at_ms: int,
        last_seen_ms: int,
        last_seq: int = -1,
        last_outbound_seq: int = 0,
        metadata: dict[str, Any] | None = None,
        telemetry: dict[str, Any] | None = None,
        closed_at_ms: int = 0,
        close_reason: str = "",
        updated_at_ms: int | None = None,
    ) -> None:
        self.db.upsert_device_session(
            device_id=device_id,
            session_id=session_id,
            state=state,
            created_at_ms=created_at_ms,
            last_seen_ms=last_seen_ms,
            last_seq=last_seq,
            last_outbound_seq=last_outbound_seq,
            metadata=metadata,
            telemetry=telemetry,
            closed_at_ms=closed_at_ms,
            close_reason=close_reason,
            updated_at_ms=updated_at_ms,
        )

    def close_device_session(
        self,
        *,
        device_id: str,
        session_id: str,
        reason: str = "",
        closed_at_ms: int | None = None,
    ) -> None:
        self.db.close_device_session(
            device_id=device_id,
            session_id=session_id,
            reason=reason,
            closed_at_ms=closed_at_ms,
        )

    def list_device_sessions(
        self,
        *,
        device_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.list_device_sessions(
            device_id=device_id,
            state=state,
            limit=limit,
            offset=offset,
        )

    def upsert_device_binding(
        self,
        *,
        device_id: str,
        device_token: str,
        status: str = "registered",
        user_id: str = "",
        activated_at_ms: int = 0,
        revoked_at_ms: int = 0,
        revoke_reason: str = "",
        metadata: dict[str, Any] | None = None,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
    ) -> None:
        self.db.upsert_device_binding(
            device_id=device_id,
            device_token=device_token,
            status=status,
            user_id=user_id,
            activated_at_ms=activated_at_ms,
            revoked_at_ms=revoked_at_ms,
            revoke_reason=revoke_reason,
            metadata=metadata,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
        )

    def get_device_binding(self, *, device_id: str) -> dict[str, Any] | None:
        return self.db.get_device_binding(device_id=device_id)

    def list_device_bindings(
        self,
        *,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.list_device_bindings(
            status=status,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    def verify_device_binding(
        self,
        *,
        device_id: str,
        device_token: str,
        require_activated: bool = True,
        allow_unbound: bool = False,
    ) -> dict[str, Any]:
        return self.db.verify_device_binding(
            device_id=device_id,
            device_token=device_token,
            require_activated=require_activated,
            allow_unbound=allow_unbound,
        )

    def create_device_operation(
        self,
        *,
        operation_id: str,
        device_id: str,
        session_id: str,
        op_type: str,
        command_type: str,
        status: str = "queued",
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
        acked_at_ms: int = 0,
    ) -> None:
        self.db.create_device_operation(
            operation_id=operation_id,
            device_id=device_id,
            session_id=session_id,
            op_type=op_type,
            command_type=command_type,
            status=status,
            payload=payload,
            result=result,
            error=error,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
            acked_at_ms=acked_at_ms,
        )

    def update_device_operation(
        self,
        *,
        operation_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
        session_id: str | None = None,
        updated_at_ms: int | None = None,
        acked_at_ms: int | None = None,
    ) -> bool:
        return self.db.update_device_operation(
            operation_id=operation_id,
            status=status,
            result=result,
            error=error,
            session_id=session_id,
            updated_at_ms=updated_at_ms,
            acked_at_ms=acked_at_ms,
        )

    def get_device_operation(self, *, operation_id: str) -> dict[str, Any] | None:
        return self.db.get_device_operation(operation_id=operation_id)

    def list_device_operations(
        self,
        *,
        device_id: str | None = None,
        status: str | None = None,
        op_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.list_device_operations(
            device_id=device_id,
            status=status,
            op_type=op_type,
            limit=limit,
            offset=offset,
        )

    def add_thought_trace(
        self,
        *,
        trace_id: str,
        session_id: str,
        source: str,
        stage: str,
        payload: dict[str, Any],
        ts: int | None = None,
    ) -> int:
        return self.db.add_thought_trace(
            trace_id=trace_id,
            session_id=session_id,
            source=source,
            stage=stage,
            payload=payload,
            ts=ts,
        )

    def list_thought_traces(
        self,
        *,
        trace_id: str | None = None,
        session_id: str | None = None,
        source: str | None = None,
        stage: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 200,
        offset: int = 0,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        return self.db.list_thought_traces(
            trace_id=trace_id,
            session_id=session_id,
            source=source,
            stage=stage,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            offset=offset,
            order=order,
        )

    def add_telemetry_sample(
        self,
        *,
        device_id: str,
        session_id: str,
        schema_version: str,
        sample: dict[str, Any],
        raw: dict[str, Any] | None = None,
        trace_id: str = "",
        ts: int | None = None,
    ) -> int:
        return self.db.add_telemetry_sample(
            device_id=device_id,
            session_id=session_id,
            schema_version=schema_version,
            sample=sample,
            raw=raw,
            trace_id=trace_id,
            ts=ts,
        )

    def list_telemetry_samples(
        self,
        *,
        device_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.list_telemetry_samples(
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=limit,
            offset=offset,
        )

    def cleanup_retention(
        self,
        *,
        runtime_events_days: int | None = None,
        thought_traces_days: int | None = None,
        device_sessions_days: int | None = None,
        device_operations_days: int | None = None,
        telemetry_samples_days: int | None = None,
        now_ms: int | None = None,
    ) -> dict[str, int]:
        return self.db.cleanup_retention(
            runtime_events_days=runtime_events_days,
            thought_traces_days=thought_traces_days,
            device_sessions_days=device_sessions_days,
            device_operations_days=device_operations_days,
            telemetry_samples_days=telemetry_samples_days,
            now_ms=now_ms,
        )

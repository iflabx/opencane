"""Mock control API server for smoke tests (no hardware, no LLM key required)."""

from __future__ import annotations

import argparse
import asyncio
import signal
import time
from typing import Any

from opencane.api.hardware_server import HardwareControlServer


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class FakeRuntime:
    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self._digital_task: Any | None = None
        self._safety_applied = 0
        self._safety_downgraded = 0

    def set_digital_task_service(self, service: Any) -> None:
        self._digital_task = service

    def mark_device_ready(self, device_id: str, session_id: str) -> None:
        did = str(device_id or "").strip()
        if not did:
            return
        self.devices[did] = {
            "device_id": did,
            "session_id": str(session_id or ""),
            "state": "ready",
            "last_seen_ms": _now_ms(),
        }

    def mark_safety(self, *, downgraded: bool) -> None:
        self._safety_applied += 1
        if downgraded:
            self._safety_downgraded += 1

    def get_runtime_status(self) -> dict[str, Any]:
        digital_stats: dict[str, Any] = {}
        if self._digital_task and hasattr(self._digital_task, "stats_snapshot"):
            digital_stats = self._digital_task.stats_snapshot()
        return {
            "adapter": "mock",
            "transport": "mock",
            "running": True,
            "metrics": {
                "events_total": 0,
                "commands_total": 0,
                "events_by_type": {},
                "commands_by_type": {},
                "duplicate_events_total": 0,
            },
            "digital_task": digital_stats,
            "safety": {
                "enabled": True,
                "applied": self._safety_applied,
                "downgraded": self._safety_downgraded,
            },
            "devices": list(self.devices.values()),
        }

    def get_device_status(self, device_id: str) -> dict[str, Any] | None:
        return self.devices.get(str(device_id or "").strip())

    async def abort(self, device_id: str, reason: str = "manual_abort") -> bool:
        del reason
        did = str(device_id or "").strip()
        if did not in self.devices:
            return False
        self.devices[did]["state"] = "ready"
        self.devices[did]["last_seen_ms"] = _now_ms()
        return True


class FakeAdapter:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime

    async def inject_event(self, event: Any) -> Any:
        device_id = str(getattr(event, "device_id", "") or "")
        session_id = str(getattr(event, "session_id", "") or "")
        event_type = str(getattr(event, "type", "") or "")
        if event_type == "hello":
            self.runtime.mark_device_ready(device_id=device_id, session_id=session_id)
        return event


class FakeLifelogService:
    def __init__(self) -> None:
        self._images_by_session: dict[str, list[dict[str, Any]]] = {}
        self._events_by_session: dict[str, list[dict[str, Any]]] = {}
        self._next_image_id = 0
        self._next_event_id = 0

    def _append_event(
        self,
        session_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        risk_level: str = "P3",
        confidence: float = 0.0,
        ts: int | None = None,
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        self._next_event_id += 1
        item = {
            "id": self._next_event_id,
            "session_id": sid,
            "event_type": str(event_type),
            "ts": int(ts or _now_ms()),
            "payload": dict(payload),
            "risk_level": str(risk_level),
            "confidence": float(confidence),
        }
        self._events_by_session.setdefault(sid, []).append(item)
        return item

    def add_safety_event(
        self,
        *,
        session_id: str,
        source: str,
        downgraded: bool,
        reason: str = "ok",
    ) -> None:
        self._append_event(
            session_id,
            event_type="safety_policy",
            payload={
                "trace_id": f"mock-trace-{self._next_event_id + 1}",
                "source": str(source),
                "reason": str(reason),
                "flags": [],
                "policy_version": "mock-v1",
                "rule_ids": [],
                "evidence": {"mock": True},
                "downgraded": bool(downgraded),
            },
            risk_level="P3",
            confidence=0.9,
        )

    def record_observability_sample(self, sample: dict[str, Any]) -> int:
        payload = {
            "healthy": bool(sample.get("healthy")),
            "metrics": dict(sample.get("metrics") or {}),
            "thresholds": dict(sample.get("thresholds") or {}),
        }
        self._append_event(
            "__runtime_observability__",
            event_type="runtime_observability",
            payload=payload,
            risk_level="P3",
            confidence=1.0,
            ts=_to_int(sample.get("ts"), _now_ms()),
        )
        return self._next_event_id

    def list_observability_samples(
        self,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = list(self._events_by_session.get("__runtime_observability__", []))
        if start_ts is not None:
            items = [item for item in items if int(item.get("ts", 0)) >= int(start_ts)]
        if end_ts is not None:
            items = [item for item in items if int(item.get("ts", 0)) <= int(end_ts)]
        items = [item for item in items if str(item.get("event_type")) == "runtime_observability"]
        items = sorted(items, key=lambda x: int(x.get("ts", 0)), reverse=True)
        off = max(0, int(offset))
        lim = max(1, int(limit))
        output: list[dict[str, Any]] = []
        for item in items[off : off + lim]:
            event_payload = item.get("payload")
            payload_map = event_payload if isinstance(event_payload, dict) else {}
            metrics = payload_map.get("metrics")
            thresholds = payload_map.get("thresholds")
            output.append(
                {
                    "ts": int(item.get("ts", 0)),
                    "healthy": bool(payload_map.get("healthy")),
                    "metrics": dict(metrics) if isinstance(metrics, dict) else {},
                    "thresholds": dict(thresholds) if isinstance(thresholds, dict) else {},
                }
            )
        return output

    async def enqueue_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        image_base64 = str(payload.get("image_base64") or payload.get("imageBase64") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        if not image_base64:
            return {"success": False, "error": "image_base64 is required"}
        self._next_image_id += 1
        image_id = self._next_image_id
        ts = _now_ms()
        image = {
            "image_id": image_id,
            "session_id": session_id,
            "question": str(payload.get("question") or ""),
            "summary": "mock summary",
            "ts": ts,
        }
        self._images_by_session.setdefault(session_id, []).append(image)
        self._append_event(
            session_id,
            event_type="image_ingested",
            payload={"image_id": image_id, "dedup": False},
            risk_level="P3",
            confidence=1.0,
            ts=ts,
        )
        return {
            "success": True,
            "session_id": session_id,
            "image_id": image_id,
            "dedup": False,
            "summary": image["summary"],
            "ts": ts,
        }

    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("q") or "").strip()
        if not query:
            return {"success": False, "error": "query is required"}
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        top_k = max(1, _to_int(payload.get("top_k"), 5))
        hits: list[dict[str, Any]] = []
        if session_id:
            images = list(self._images_by_session.get(session_id, []))
        else:
            images = [item for arr in self._images_by_session.values() for item in arr]
        for item in sorted(images, key=lambda x: int(x.get("ts", 0)), reverse=True)[:top_k]:
            hits.append(
                {
                    "id": str(item["image_id"]),
                    "text": f"mock:{query}",
                    "metadata": {
                        "session_id": item["session_id"],
                        "ts": item["ts"],
                        "image_id": item["image_id"],
                        "dedup": False,
                    },
                    "score": 1.0,
                }
            )
        return {"success": True, "query": query, "top_k": top_k, "hits": hits}

    async def timeline_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        limit = max(1, _to_int(payload.get("limit"), 50))
        offset = max(0, _to_int(payload.get("offset"), 0))
        event_type = str(payload.get("event_type") or payload.get("eventType") or "").strip()
        risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "").strip()
        items = list(self._events_by_session.get(session_id, []))
        if event_type:
            items = [item for item in items if str(item.get("event_type")) == event_type]
        if risk_level:
            items = [item for item in items if str(item.get("risk_level")) == risk_level]
        items = sorted(items, key=lambda x: int(x.get("ts", 0)), reverse=True)
        paged = items[offset : offset + limit]
        return {
            "success": True,
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "count": len(paged),
            "items": paged,
        }

    async def safety_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        trace_id = str(payload.get("trace_id") or payload.get("traceId") or "").strip()
        source = str(payload.get("source") or "").strip()
        downgraded_filter = payload.get("downgraded")
        downgraded = None if downgraded_filter is None else _to_bool(downgraded_filter)
        limit = max(1, _to_int(payload.get("limit"), 50))
        offset = max(0, _to_int(payload.get("offset"), 0))

        items = [
            item
            for item in self._events_by_session.get(session_id, [])
            if str(item.get("event_type")) == "safety_policy"
        ]
        items = sorted(items, key=lambda x: int(x.get("ts", 0)), reverse=True)
        filtered: list[dict[str, Any]] = []
        for item in items:
            event_payload = item.get("payload")
            payload_map = event_payload if isinstance(event_payload, dict) else {}
            if trace_id and str(payload_map.get("trace_id") or "") != trace_id:
                continue
            if source and str(payload_map.get("source") or "") != source:
                continue
            if downgraded is not None and bool(payload_map.get("downgraded")) != downgraded:
                continue
            filtered.append(item)
        paged = filtered[offset : offset + limit]
        return {
            "success": True,
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "count": len(paged),
            "items": paged,
            "filters": {
                "trace_id": trace_id,
                "source": source,
                "risk_level": str(payload.get("risk_level") or payload.get("riskLevel") or "") or None,
                "downgraded": downgraded,
                "start_ts": None,
                "end_ts": None,
            },
        }

    async def safety_stats(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        items = [
            item
            for item in self._events_by_session.get(session_id, [])
            if str(item.get("event_type")) == "safety_policy"
        ]
        total = len(items)
        downgraded = 0
        by_source: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        for item in items:
            event_payload = item.get("payload")
            payload_map = event_payload if isinstance(event_payload, dict) else {}
            source = str(payload_map.get("source") or "unknown")
            reason = str(payload_map.get("reason") or "unknown")
            by_source[source] = int(by_source.get(source, 0)) + 1
            by_reason[reason] = int(by_reason.get(reason, 0)) + 1
            if bool(payload_map.get("downgraded")):
                downgraded += 1
        rate = (float(downgraded) / float(total)) if total > 0 else 0.0
        return {
            "success": True,
            "session_id": session_id,
            "filters": {
                "source": str(payload.get("source") or ""),
                "risk_level": str(payload.get("risk_level") or payload.get("riskLevel") or "") or None,
                "start_ts": None,
                "end_ts": None,
            },
            "summary": {
                "total": total,
                "downgraded": downgraded,
                "downgrade_rate": round(rate, 4),
            },
            "by_source": by_source,
            "by_risk_level": {"P3": total} if total else {},
            "by_reason": by_reason,
            "by_rule_id": {},
            "by_policy_version": {"mock-v1": total} if total else {},
        }


class FakeDigitalTaskService:
    def __init__(
        self,
        *,
        lifelog: FakeLifelogService,
        on_safety: Any,
    ) -> None:
        self.lifelog = lifelog
        self.on_safety = on_safety
        self.tasks: dict[str, dict[str, Any]] = {}
        self._next_id = 0

    def stats_snapshot(self, *, session_id: str | None = None) -> dict[str, Any]:
        items = list(self.tasks.values())
        if session_id:
            items = [item for item in items if str(item.get("session_id")) == session_id]
        total = len(items)
        success = len([item for item in items if str(item.get("status")) == "success"])
        failed = len([item for item in items if str(item.get("status")) == "failed"])
        timeout = len([item for item in items if str(item.get("status")) == "timeout"])
        canceled = len([item for item in items if str(item.get("status")) == "canceled"])
        pending = len([item for item in items if str(item.get("status")) == "pending"])
        running = len([item for item in items if str(item.get("status")) == "running"])
        success_rate = (float(success) / float(total)) if total > 0 else 0.0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "timeout": timeout,
            "canceled": canceled,
            "pending": pending,
            "running": running,
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": 0.0,
            "avg_step_count": 0.0,
            "counts_by_status": {},
        }

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = str(payload.get("goal") or payload.get("prompt") or "").strip()
        if not goal:
            return {"success": False, "error": "goal is required", "error_code": "bad_request"}
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or "sess-mock"
        self._next_id += 1
        task_id = f"task-{self._next_id}"
        now = _now_ms()
        task = {
            "task_id": task_id,
            "session_id": session_id,
            "goal": goal,
            "status": "running",
            "steps": [
                {
                    "stage": "accepted",
                    "status": "ok",
                    "message": "task accepted",
                    "ts": now,
                }
            ],
            "result": {},
            "error": "",
            "created_at": now,
            "updated_at": now,
        }
        self.tasks[task_id] = task
        self.lifelog.add_safety_event(
            session_id=session_id,
            source="task_update",
            downgraded=False,
            reason="ok",
        )
        self.on_safety(downgraded=False)
        return {"success": True, "accepted": True, "task": task}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(str(task_id))
        if task is None:
            return {"success": False, "error": "task not found", "error_code": "not_found"}
        return {"success": True, "task": task}

    async def list_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        status_filter = str(payload.get("status") or "").strip()
        limit = max(1, _to_int(payload.get("limit"), 20))
        offset = max(0, _to_int(payload.get("offset"), 0))
        items = list(self.tasks.values())
        if session_id:
            items = [item for item in items if str(item.get("session_id")) == session_id]
        if status_filter:
            items = [item for item in items if str(item.get("status")) == status_filter]
        items = sorted(items, key=lambda x: int(x.get("created_at", 0)), reverse=True)
        paged = items[offset : offset + limit]
        return {"success": True, "count": len(paged), "items": paged}

    async def stats(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or None
        return {"success": True, "session_id": session_id, "stats": self.stats_snapshot(session_id=session_id)}

    async def cancel(self, task_id: str, reason: str = "manual_cancel") -> dict[str, Any]:
        task = self.tasks.get(str(task_id))
        if task is None:
            return {"success": False, "error": "task not found", "error_code": "not_found"}
        task["status"] = "canceled"
        task["error"] = str(reason or "manual_cancel")
        task["updated_at"] = _now_ms()
        return {"success": True, "task": task}


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock control API server for smoke scripts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18792)
    parser.add_argument("--auth-token", default="")
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    runtime = FakeRuntime()
    lifelog = FakeLifelogService()
    digital_task = FakeDigitalTaskService(
        lifelog=lifelog,
        on_safety=runtime.mark_safety,
    )
    runtime.set_digital_task_service(digital_task)
    adapter = FakeAdapter(runtime)
    server = HardwareControlServer(
        host=str(args.host),
        port=int(args.port),
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=lifelog,  # type: ignore[arg-type]
        adapter=adapter,  # type: ignore[arg-type]
        loop=loop,
        digital_task=digital_task,  # type: ignore[arg-type]
        auth_enabled=bool(str(args.auth_token).strip()),
        auth_token=str(args.auth_token),
    )
    server.start()
    print(f"mock control api ready on http://{args.host}:{args.port}", flush=True)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(stop_event.wait())
    finally:
        server.stop()
        loop.close()


if __name__ == "__main__":
    main()

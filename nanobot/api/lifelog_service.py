"""Lifelog API service wrapping P2 vision pipeline primitives."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import Config
from nanobot.storage import ChromaLifelogIndex, QdrantLifelogIndex, SQLiteLifelogStore
from nanobot.vision import (
    ImageAssetStore,
    LifelogTimelineService,
    VisionIndexer,
    VisionLifelogPipeline,
    VisionLifelogStore,
)


@dataclass(slots=True)
class _IngestJob:
    session_id: str
    image_base64: str
    question: str
    mime: str
    metadata: dict[str, Any]
    ts: int | None
    future: asyncio.Future[dict[str, Any]]


class LifelogService:
    """Application service exposing enqueue/query/timeline operations."""

    OBSERVABILITY_SESSION_ID = "__runtime_observability__"
    OBSERVABILITY_EVENT_TYPE = "runtime_observability"
    _INGEST_SENTINEL: object = object()

    def __init__(
        self,
        *,
        store: VisionLifelogStore,
        indexer: VisionIndexer,
        pipeline: VisionLifelogPipeline,
        timeline: LifelogTimelineService,
        default_top_k: int = 5,
        max_timeline_items: int = 200,
        ingest_queue_max_size: int = 64,
        ingest_workers: int = 2,
        ingest_overflow_policy: str = "reject",
        ingest_enqueue_timeout_ms: int = 500,
    ) -> None:
        self.store = store
        self.indexer = indexer
        self.pipeline = pipeline
        self.timeline = timeline
        self.default_top_k = max(1, int(default_top_k))
        self.max_timeline_items = max(1, int(max_timeline_items))
        self.ingest_queue_max_size = max(1, int(ingest_queue_max_size))
        self.ingest_workers = max(1, int(ingest_workers))
        policy = str(ingest_overflow_policy or "reject").strip().lower()
        if policy not in {"reject", "wait", "drop_oldest"}:
            policy = "reject"
        self.ingest_overflow_policy = policy
        self.ingest_enqueue_timeout_ms = max(1, int(ingest_enqueue_timeout_ms))

        self._ingest_queue: asyncio.Queue[_IngestJob | object] | None = None
        self._ingest_worker_tasks: list[asyncio.Task[None]] = []
        self._ingest_loop: asyncio.AbstractEventLoop | None = None
        self._ingest_started = False
        self._ingest_shutdown = False

        self._ingest_enqueued_total = 0
        self._ingest_processed_total = 0
        self._ingest_failed_total = 0
        self._ingest_rejected_total = 0
        self._ingest_dropped_total = 0
        self._ingest_in_flight = 0
        self._ingest_latency_total_ms = 0.0
        self._ingest_latency_samples = 0
        self._ingest_max_depth = 0

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        analyzer: Any | None = None,
    ) -> "LifelogService":
        sqlite_path = Path(config.lifelog.sqlite_path).expanduser()
        chroma_dir = Path(config.lifelog.chroma_persist_dir).expanduser()
        image_asset_dir = Path(config.lifelog.image_asset_dir).expanduser()
        chroma_dir.mkdir(parents=True, exist_ok=True)
        image_asset_dir.mkdir(parents=True, exist_ok=True)
        sqlite_store = SQLiteLifelogStore(sqlite_path)
        store = VisionLifelogStore(sqlite_store)
        asset_store = ImageAssetStore(
            image_asset_dir,
            max_files=max(100, int(config.lifelog.image_asset_max_files)),
        )
        vector_backend = str(config.lifelog.vector_backend or "chroma").strip().lower()
        index_backend: Any
        if vector_backend == "qdrant":
            try:
                index_backend = QdrantLifelogIndex(
                    collection_name=str(config.lifelog.qdrant_collection or "lifelog_semantic"),
                    url=config.lifelog.qdrant_url,
                    api_key=config.lifelog.qdrant_api_key,
                    timeout_seconds=config.lifelog.qdrant_timeout_seconds,
                )
            except Exception as e:
                logger.warning(f"qdrant backend init failed, fallback to chroma: {e}")
                index_backend = ChromaLifelogIndex(
                    collection_name="lifelog_semantic",
                    persist_dir=str(chroma_dir),
                )
        else:
            if vector_backend != "chroma":
                logger.warning(f"unknown lifelog.vector_backend={vector_backend}, fallback to chroma")
            index_backend = ChromaLifelogIndex(
                collection_name="lifelog_semantic",
                persist_dir=str(chroma_dir),
            )
        indexer = VisionIndexer(index_backend)
        pipeline = VisionLifelogPipeline(
            store=store,
            indexer=indexer,
            analyzer=analyzer,
            asset_store=asset_store,
            dedup_max_distance=config.lifelog.dedup_max_distance,
        )
        timeline = LifelogTimelineService(store)
        logger.info(
            "Lifelog service ready "
            f"sqlite={sqlite_path} chroma={chroma_dir} images={image_asset_dir} "
            f"vector={vector_backend}/{getattr(index_backend, 'backend_mode', 'unknown')} "
            f"default_top_k={config.lifelog.default_top_k} "
            f"ingest_queue={config.lifelog.ingest_queue_max_size} "
            f"workers={config.lifelog.ingest_workers} "
            f"policy={config.lifelog.ingest_overflow_policy}"
        )
        return cls(
            store=store,
            indexer=indexer,
            pipeline=pipeline,
            timeline=timeline,
            default_top_k=config.lifelog.default_top_k,
            max_timeline_items=config.lifelog.max_timeline_items,
            ingest_queue_max_size=config.lifelog.ingest_queue_max_size,
            ingest_workers=config.lifelog.ingest_workers,
            ingest_overflow_policy=config.lifelog.ingest_overflow_policy,
            ingest_enqueue_timeout_ms=config.lifelog.ingest_enqueue_timeout_ms,
        )

    async def shutdown(self) -> None:
        if self._ingest_shutdown:
            return
        self._ingest_shutdown = True
        queue = self._ingest_queue
        tasks = [task for task in self._ingest_worker_tasks if not task.done()]
        if queue is not None and tasks:
            for _ in tasks:
                await queue.put(self._INGEST_SENTINEL)
            await asyncio.gather(*tasks, return_exceptions=True)
        self._ingest_worker_tasks.clear()
        self._ingest_queue = None
        self._ingest_started = False
        self._ingest_in_flight = 0
        self.store.close()

    def close(self) -> None:
        if self._ingest_shutdown:
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not None:
            running_loop.create_task(self.shutdown())
            return
        loop = self._ingest_loop
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self.shutdown(), loop)
            try:
                fut.result(timeout=3)
            except Exception:
                pass
            return
        self._ingest_shutdown = True
        self.store.close()

    def status_snapshot(self) -> dict[str, Any]:
        vector = self.indexer.status_snapshot() if hasattr(self.indexer, "status_snapshot") else {}
        return {
            "enabled": True,
            "vector_index": vector,
            "ingest_queue": self._ingest_queue_snapshot(),
        }

    def record_runtime_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        risk_level: str = "P3",
        confidence: float = 0.0,
        ts: int | None = None,
    ) -> int:
        """Persist runtime event into lifelog event table."""
        event_id = self.store.record_event(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            risk_level=risk_level,
            confidence=confidence,
            ts=int(ts) if ts is not None else None,
        )
        trace_id = _extract_trace_id(payload)
        if trace_id and hasattr(self.store, "add_thought_trace"):
            try:
                self.store.add_thought_trace(
                    trace_id=trace_id,
                    session_id=session_id,
                    source=f"runtime:{str(event_type or '')}",
                    stage=str(event_type or ""),
                    payload={
                        "event_id": event_id,
                        "risk_level": str(risk_level or "P3"),
                        "confidence": float(confidence),
                        "payload": dict(payload or {}),
                    },
                    ts=int(ts) if ts is not None else None,
                )
            except Exception as e:
                logger.debug(f"thought trace append from runtime event failed: {e}")
        return event_id

    def record_observability_sample(self, sample: dict[str, Any]) -> int:
        """Persist one runtime observability sample for history queries."""
        ts = _to_int(sample.get("ts"))
        payload = {
            "healthy": bool(sample.get("healthy")),
            "metrics": dict(sample.get("metrics") or {}),
            "thresholds": dict(sample.get("thresholds") or {}),
        }
        return self.record_runtime_event(
            session_id=self.OBSERVABILITY_SESSION_ID,
            event_type=self.OBSERVABILITY_EVENT_TYPE,
            payload=payload,
            risk_level="P3",
            confidence=1.0,
            ts=ts,
        )

    def list_observability_samples(
        self,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = self.timeline.list_timeline(
            session_id=self.OBSERVABILITY_SESSION_ID,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type=self.OBSERVABILITY_EVENT_TYPE,
            risk_level=None,
            limit=max(1, int(limit)),
            offset=max(0, int(offset)),
        )
        output: list[dict[str, Any]] = []
        for item in items:
            payload = item.get("payload")
            payload_map = payload if isinstance(payload, dict) else {}
            metrics = payload_map.get("metrics")
            thresholds = payload_map.get("thresholds")
            output.append(
                {
                    "ts": int(item.get("ts") or 0),
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

        question = str(payload.get("question") or payload.get("prompt") or "")
        mime = str(payload.get("mime") or "image/jpeg")
        ts = _to_int(payload.get("ts"))
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        try:
            await self._ensure_ingest_workers()
            result = await self._enqueue_ingest_job(
                session_id=session_id,
                image_base64=image_base64,
                question=question,
                mime=mime,
                metadata=metadata,
                ts=ts,
            )
            if not isinstance(result, dict):
                return {"success": True, "result": str(result)}
            if "success" not in result:
                result = {"success": True, **result}
            return result
        except Exception as e:
            logger.warning(f"lifelog enqueue failed: {e}")
            return {"success": False, "error": str(e)}

    async def _ensure_ingest_workers(self) -> None:
        if self._ingest_shutdown:
            raise RuntimeError("lifelog service is shut down")
        loop = asyncio.get_running_loop()
        if self._ingest_started and self._ingest_loop is loop:
            alive = [task for task in self._ingest_worker_tasks if not task.done()]
            if len(alive) == self.ingest_workers:
                return
            self._ingest_worker_tasks = alive
        if self._ingest_queue is None or self._ingest_loop is not loop:
            self._ingest_queue = asyncio.Queue(maxsize=self.ingest_queue_max_size)
            self._ingest_loop = loop
            self._ingest_worker_tasks = []
            self._ingest_started = True
        while len(self._ingest_worker_tasks) < self.ingest_workers:
            idx = len(self._ingest_worker_tasks)
            self._ingest_worker_tasks.append(asyncio.create_task(self._ingest_worker(idx)))

    async def _enqueue_ingest_job(
        self,
        *,
        session_id: str,
        image_base64: str,
        question: str,
        mime: str,
        metadata: dict[str, Any],
        ts: int | None,
    ) -> dict[str, Any]:
        queue = self._ingest_queue
        if queue is None:
            raise RuntimeError("ingest queue is not initialized")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        job = _IngestJob(
            session_id=session_id,
            image_base64=image_base64,
            question=question,
            mime=mime,
            metadata=dict(metadata),
            ts=ts,
            future=future,
        )
        policy = self.ingest_overflow_policy
        if policy == "wait":
            try:
                await asyncio.wait_for(
                    queue.put(job),
                    timeout=float(self.ingest_enqueue_timeout_ms) / 1000.0,
                )
            except asyncio.TimeoutError:
                self._ingest_rejected_total += 1
                return {
                    "success": False,
                    "error": "ingest queue is full",
                    "error_code": "queue_full",
                    "queue": self._ingest_queue_snapshot(),
                }
        elif policy == "drop_oldest":
            if queue.full():
                dropped = queue.get_nowait()
                queue.task_done()
                self._ingest_dropped_total += 1
                if isinstance(dropped, _IngestJob) and not dropped.future.done():
                    dropped.future.set_result(
                        {
                            "success": False,
                            "error": "ingest queue dropped by overflow policy",
                            "error_code": "queue_dropped",
                            "queue": self._ingest_queue_snapshot(),
                        }
                    )
            queue.put_nowait(job)
        else:
            if queue.full():
                self._ingest_rejected_total += 1
                return {
                    "success": False,
                    "error": "ingest queue is full",
                    "error_code": "queue_full",
                    "queue": self._ingest_queue_snapshot(),
                }
            queue.put_nowait(job)
        self._ingest_enqueued_total += 1
        self._ingest_max_depth = max(self._ingest_max_depth, int(queue.qsize()))
        return await future

    async def _ingest_worker(self, idx: int) -> None:
        del idx
        queue = self._ingest_queue
        if queue is None:
            return
        while True:
            item = await queue.get()
            if item is self._INGEST_SENTINEL:
                queue.task_done()
                return
            if not isinstance(item, _IngestJob):
                queue.task_done()
                continue
            self._ingest_in_flight += 1
            started = time.perf_counter()
            try:
                result = await self.pipeline.ingest_image(
                    session_id=item.session_id,
                    image_base64=item.image_base64,
                    question=item.question,
                    mime=item.mime,
                    metadata=item.metadata,
                    ts=item.ts,
                )
                if not isinstance(result, dict):
                    result = {"success": True, "result": str(result)}
                if "success" not in result:
                    result = {"success": True, **result}
                self._ingest_processed_total += 1
            except Exception as e:
                logger.warning(f"lifelog ingest worker failed: {e}")
                self._ingest_failed_total += 1
                result = {"success": False, "error": str(e)}
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                self._ingest_latency_total_ms += elapsed_ms
                self._ingest_latency_samples += 1
                self._ingest_in_flight = max(0, self._ingest_in_flight - 1)
                queue.task_done()
            if not item.future.done():
                item.future.set_result(result)

    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("q") or "").strip()
        if not query:
            return {"success": False, "error": "query is required"}
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        top_k = _to_int(payload.get("top_k"), default=self.default_top_k) or self.default_top_k
        risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "").strip() or None
        has_objects = _to_bool(payload.get("has_objects") if "has_objects" in payload else payload.get("hasObjects"))
        has_ocr = _to_bool(payload.get("has_ocr") if "has_ocr" in payload else payload.get("hasOcr"))
        has_risk_hints = _to_bool(
            payload.get("has_risk_hints") if "has_risk_hints" in payload else payload.get("hasRiskHints")
        )
        object_contains = str(payload.get("object_contains") or payload.get("objectContains") or "").strip()
        ocr_contains = str(payload.get("ocr_contains") or payload.get("ocrContains") or "").strip()
        risk_hint_contains = str(payload.get("risk_hint_contains") or payload.get("riskHintContains") or "").strip()
        include_context_raw = _to_bool(
            payload.get("include_context") if "include_context" in payload else payload.get("includeContext")
        )
        include_context = True if include_context_raw is None else bool(include_context_raw)

        where: dict[str, Any] = {}
        if session_id:
            where["session_id"] = session_id
        if risk_level:
            where["risk_level"] = risk_level
        if has_objects is not None:
            where["has_objects"] = 1 if has_objects else 0
        if has_ocr is not None:
            where["has_ocr"] = 1 if has_ocr else 0
        if has_risk_hints is not None:
            where["has_risk_hints"] = 1 if has_risk_hints else 0
        where_filter = where or None

        need_text_post_filter = bool(object_contains or ocr_contains or risk_hint_contains)
        search_top_k = max(1, int(top_k))
        if need_text_post_filter:
            search_top_k = max(search_top_k * 4, search_top_k + 5)
        hits = self.indexer.search(query=query, top_k=search_top_k, where=where_filter)

        image_ids: list[int] = []
        for hit in hits:
            metadata = hit.get("metadata")
            meta = metadata if isinstance(metadata, dict) else {}
            image_id = _extract_int(meta.get("image_id"), default=0)
            if image_id <= 0:
                image_id = _extract_int(hit.get("id"), default=0)
            if image_id > 0:
                image_ids.append(image_id)
        contexts = self.store.get_contexts_by_image_ids(image_ids=image_ids)

        filtered_hits: list[dict[str, Any]] = []
        for hit in hits:
            item = dict(hit)
            metadata = item.get("metadata")
            meta = metadata if isinstance(metadata, dict) else {}
            image_id = _extract_int(meta.get("image_id"), default=0)
            if image_id <= 0:
                image_id = _extract_int(item.get("id"), default=0)
            context = contexts.get(image_id)
            if not _structured_context_matches(
                context,
                has_objects=has_objects,
                has_ocr=has_ocr,
                has_risk_hints=has_risk_hints,
                object_contains=object_contains,
                ocr_contains=ocr_contains,
                risk_hint_contains=risk_hint_contains,
            ):
                continue
            if include_context and context is not None:
                item["structured_context"] = context
            filtered_hits.append(item)
            if len(filtered_hits) >= max(1, int(top_k)):
                break

        return {
            "success": True,
            "query": query,
            "top_k": max(1, top_k),
            "hits": filtered_hits,
            "filters": {
                "session_id": session_id,
                "risk_level": risk_level,
                "has_objects": has_objects,
                "has_ocr": has_ocr,
                "has_risk_hints": has_risk_hints,
                "object_contains": object_contains,
                "ocr_contains": ocr_contains,
                "risk_hint_contains": risk_hint_contains,
            },
        }

    async def timeline_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        start_ts = _to_int(payload.get("start_ts"))
        end_ts = _to_int(payload.get("end_ts"))
        event_type = str(payload.get("event_type") or payload.get("eventType") or "").strip() or None
        risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "").strip() or None
        has_objects = _to_bool(payload.get("has_objects") if "has_objects" in payload else payload.get("hasObjects"))
        has_ocr = _to_bool(payload.get("has_ocr") if "has_ocr" in payload else payload.get("hasOcr"))
        has_risk_hints = _to_bool(
            payload.get("has_risk_hints") if "has_risk_hints" in payload else payload.get("hasRiskHints")
        )
        object_contains = str(payload.get("object_contains") or payload.get("objectContains") or "").strip()
        ocr_contains = str(payload.get("ocr_contains") or payload.get("ocrContains") or "").strip()
        risk_hint_contains = str(payload.get("risk_hint_contains") or payload.get("riskHintContains") or "").strip()
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)
        limit = _to_int(payload.get("limit"), default=50) or 50
        limit = min(max(1, limit), self.max_timeline_items)
        structured_filters_enabled = any(
            value is not None
            for value in (has_objects, has_ocr, has_risk_hints)
        ) or bool(object_contains or ocr_contains or risk_hint_contains)

        if not structured_filters_enabled:
            items = self.timeline.list_timeline(
                session_id=session_id,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type=event_type,
                risk_level=risk_level,
                limit=limit,
                offset=offset,
            )
            return {
                "success": True,
                "session_id": session_id,
                "offset": offset,
                "limit": limit,
                "count": len(items),
                "items": items,
            }

        batch_size = min(self.max_timeline_items, max(50, limit))
        scan_offset = 0
        matched = 0
        filtered: list[dict[str, Any]] = []
        while len(filtered) < limit:
            items = self.timeline.list_timeline(
                session_id=session_id,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type=event_type,
                risk_level=risk_level,
                limit=batch_size,
                offset=scan_offset,
            )
            if not items:
                break
            scan_offset += len(items)
            for item in items:
                context = _extract_structured_context_from_event(item)
                if not _structured_context_matches(
                    context,
                    has_objects=has_objects,
                    has_ocr=has_ocr,
                    has_risk_hints=has_risk_hints,
                    object_contains=object_contains,
                    ocr_contains=ocr_contains,
                    risk_hint_contains=risk_hint_contains,
                ):
                    continue
                if matched < offset:
                    matched += 1
                    continue
                filtered.append(item)
                if len(filtered) >= limit:
                    break
            if len(items) < batch_size:
                break
        return {
            "success": True,
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "count": len(filtered),
            "items": filtered,
            "filters": {
                "event_type": event_type,
                "risk_level": risk_level,
                "has_objects": has_objects,
                "has_ocr": has_ocr,
                "has_risk_hints": has_risk_hints,
                "object_contains": object_contains,
                "ocr_contains": ocr_contains,
                "risk_hint_contains": risk_hint_contains,
                "start_ts": start_ts,
                "end_ts": end_ts,
            },
        }

    async def safety_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Query safety-policy audit events."""
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        start_ts = _to_int(payload.get("start_ts"))
        end_ts = _to_int(payload.get("end_ts"))
        trace_id = str(payload.get("trace_id") or payload.get("traceId") or "").strip()
        source = str(payload.get("source") or "").strip()
        risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "").strip() or None
        downgraded = _to_bool(payload.get("downgraded"))
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)

        limit = _to_int(payload.get("limit"), default=50) or 50
        limit = min(max(1, limit), self.max_timeline_items)

        # Scan safety events with pagination to avoid fixed-window truncation.
        batch_size = min(self.max_timeline_items, max(50, limit))
        scan_offset = 0
        matched = 0
        filtered: list[dict[str, Any]] = []
        while len(filtered) < limit:
            items = self.timeline.list_timeline(
                session_id=session_id,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="safety_policy",
                risk_level=risk_level,
                limit=batch_size,
                offset=scan_offset,
            )
            if not items:
                break
            scan_offset += len(items)
            for item in items:
                event_payload = item.get("payload")
                payload_map = event_payload if isinstance(event_payload, dict) else {}
                if trace_id:
                    event_trace = str(payload_map.get("trace_id") or payload_map.get("traceId") or "").strip()
                    if event_trace != trace_id:
                        continue
                if source:
                    event_source = str(payload_map.get("source") or "").strip()
                    if event_source != source:
                        continue
                if downgraded is not None:
                    if bool(payload_map.get("downgraded")) != bool(downgraded):
                        continue
                if matched < offset:
                    matched += 1
                    continue
                filtered.append(item)
                if len(filtered) >= limit:
                    break
            if len(items) < batch_size:
                break
        return {
            "success": True,
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "count": len(filtered),
            "items": filtered,
            "filters": {
                "trace_id": trace_id,
                "source": source,
                "risk_level": risk_level,
                "downgraded": downgraded,
                "start_ts": start_ts,
                "end_ts": end_ts,
            },
        }

    async def safety_stats(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Aggregate safety-policy audit metrics for one session."""
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        start_ts = _to_int(payload.get("start_ts"))
        end_ts = _to_int(payload.get("end_ts"))
        source = str(payload.get("source") or "").strip()
        risk_level = str(payload.get("risk_level") or payload.get("riskLevel") or "").strip() or None

        batch_size = self.max_timeline_items
        scan_offset = 0
        total = 0
        downgraded_count = 0
        by_source: dict[str, int] = defaultdict(int)
        by_risk: dict[str, int] = defaultdict(int)
        by_reason: dict[str, int] = defaultdict(int)
        by_rule: dict[str, int] = defaultdict(int)
        by_policy_version: dict[str, int] = defaultdict(int)

        while True:
            items = self.timeline.list_timeline(
                session_id=session_id,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="safety_policy",
                risk_level=risk_level,
                limit=batch_size,
                offset=scan_offset,
            )
            if not items:
                break
            scan_offset += len(items)
            for item in items:
                event_payload = item.get("payload")
                payload_map = event_payload if isinstance(event_payload, dict) else {}
                event_source = str(payload_map.get("source") or "").strip()
                if source and event_source != source:
                    continue
                event_risk = str(item.get("risk_level") or "P3")
                event_reason = str(payload_map.get("reason") or "unknown")
                event_policy_version = str(payload_map.get("policy_version") or "unknown")
                total += 1
                by_source[event_source or "unknown"] += 1
                by_risk[event_risk] += 1
                by_reason[event_reason] += 1
                by_policy_version[event_policy_version] += 1
                if bool(payload_map.get("downgraded")):
                    downgraded_count += 1
                rule_ids = payload_map.get("rule_ids")
                if isinstance(rule_ids, list):
                    for rule_id in rule_ids:
                        key = str(rule_id).strip()
                        if key:
                            by_rule[key] += 1
            if len(items) < batch_size:
                break

        downgrade_rate = 0.0 if total == 0 else float(downgraded_count) / float(total)
        return {
            "success": True,
            "session_id": session_id,
            "filters": {
                "source": source,
                "risk_level": risk_level,
                "start_ts": start_ts,
                "end_ts": end_ts,
            },
            "summary": {
                "total": total,
                "downgraded": downgraded_count,
                "downgrade_rate": round(downgrade_rate, 4),
            },
            "by_source": _sort_count_dict(by_source),
            "by_risk_level": _sort_count_dict(by_risk),
            "by_reason": _sort_count_dict(by_reason),
            "by_rule_id": _sort_count_dict(by_rule),
            "by_policy_version": _sort_count_dict(by_policy_version),
        }

    async def device_sessions_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Query persisted hardware device session lifecycle rows."""
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip() or None
        state = str(payload.get("state") or "").strip() or None
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)
        limit = _to_int(payload.get("limit"), default=100) or 100
        limit = min(max(1, limit), 1000)
        if not hasattr(self.store, "list_device_sessions"):
            return {"success": False, "error": "device session storage is unavailable"}
        try:
            items = self.store.list_device_sessions(
                device_id=device_id,
                state=state,
                limit=limit,
                offset=offset,
            )
            return {
                "success": True,
                "filters": {
                    "device_id": device_id,
                    "state": state,
                    "limit": limit,
                    "offset": offset,
                },
                "count": len(items),
                "items": items,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def device_register(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        force_rotate = bool(_to_bool(payload.get("force_rotate")))
        token = str(payload.get("device_token") or payload.get("deviceToken") or "").strip()
        metadata = payload.get("metadata")
        metadata_map = metadata if isinstance(metadata, dict) else {}
        existing = self.store.get_device_binding(device_id=device_id) if hasattr(self.store, "get_device_binding") else None
        if not token and existing and not force_rotate:
            token = str(existing.get("device_token") or "")
        if not token:
            token = secrets.token_hex(16)
        now = int(time.time() * 1000)
        self.store.upsert_device_binding(
            device_id=device_id,
            device_token=token,
            status="registered",
            user_id=str(existing.get("user_id") or "") if isinstance(existing, dict) else "",
            activated_at_ms=int(existing.get("activated_at_ms") or 0) if isinstance(existing, dict) else 0,
            revoked_at_ms=0,
            revoke_reason="",
            metadata=metadata_map,
            created_at_ms=int(existing.get("created_at_ms") or now) if isinstance(existing, dict) else now,
            updated_at_ms=now,
        )
        item = self.store.get_device_binding(device_id=device_id)
        return {"success": True, "device": item}

    async def device_bind(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        if not user_id:
            return {"success": False, "error": "user_id is required"}
        existing = self.store.get_device_binding(device_id=device_id) if hasattr(self.store, "get_device_binding") else None
        if not isinstance(existing, dict):
            return {"success": False, "error": "device is not registered"}
        status = str(payload.get("status") or "bound").strip().lower()
        if status not in {"bound", "activated"}:
            status = "bound"
        now = int(time.time() * 1000)
        activated_at_ms = int(existing.get("activated_at_ms") or 0)
        if status == "activated" and activated_at_ms <= 0:
            activated_at_ms = now
        metadata = payload.get("metadata")
        metadata_map = metadata if isinstance(metadata, dict) else dict(existing.get("metadata") or {})
        self.store.upsert_device_binding(
            device_id=device_id,
            device_token=str(existing.get("device_token") or ""),
            status=status,
            user_id=user_id,
            activated_at_ms=activated_at_ms,
            revoked_at_ms=0,
            revoke_reason="",
            metadata=metadata_map,
            created_at_ms=int(existing.get("created_at_ms") or now),
            updated_at_ms=now,
        )
        item = self.store.get_device_binding(device_id=device_id)
        return {"success": True, "device": item}

    async def device_activate(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        existing = self.store.get_device_binding(device_id=device_id) if hasattr(self.store, "get_device_binding") else None
        if not isinstance(existing, dict):
            return {"success": False, "error": "device is not registered"}
        now = int(time.time() * 1000)
        self.store.upsert_device_binding(
            device_id=device_id,
            device_token=str(existing.get("device_token") or ""),
            status="activated",
            user_id=str(existing.get("user_id") or ""),
            activated_at_ms=now,
            revoked_at_ms=0,
            revoke_reason="",
            metadata=dict(existing.get("metadata") or {}),
            created_at_ms=int(existing.get("created_at_ms") or now),
            updated_at_ms=now,
        )
        item = self.store.get_device_binding(device_id=device_id)
        return {"success": True, "device": item}

    async def device_revoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        existing = self.store.get_device_binding(device_id=device_id) if hasattr(self.store, "get_device_binding") else None
        if not isinstance(existing, dict):
            return {"success": False, "error": "device is not registered"}
        reason = str(payload.get("reason") or "revoked").strip()
        now = int(time.time() * 1000)
        self.store.upsert_device_binding(
            device_id=device_id,
            device_token=str(existing.get("device_token") or ""),
            status="revoked",
            user_id=str(existing.get("user_id") or ""),
            activated_at_ms=int(existing.get("activated_at_ms") or 0),
            revoked_at_ms=now,
            revoke_reason=reason,
            metadata=dict(existing.get("metadata") or {}),
            created_at_ms=int(existing.get("created_at_ms") or now),
            updated_at_ms=now,
        )
        item = self.store.get_device_binding(device_id=device_id)
        return {"success": True, "device": item}

    async def device_binding_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        if device_id:
            item = self.store.get_device_binding(device_id=device_id) if hasattr(self.store, "get_device_binding") else None
            return {"success": True, "count": 1 if item else 0, "items": [item] if item else []}
        status = str(payload.get("status") or "").strip() or None
        user_id = str(payload.get("user_id") or payload.get("userId") or "").strip() or None
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)
        limit = _to_int(payload.get("limit"), default=100) or 100
        limit = min(max(1, limit), 1000)
        items = self.store.list_device_bindings(
            status=status,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "filters": {"status": status, "user_id": user_id, "limit": limit, "offset": offset},
            "count": len(items),
            "items": items,
        }

    def validate_device_auth(
        self,
        *,
        device_id: str,
        device_token: str,
        require_activated: bool = True,
        allow_unbound: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.store, "verify_device_binding"):
            return {"success": False, "reason": "device_binding_storage_unavailable", "binding": None}
        return self.store.verify_device_binding(
            device_id=device_id,
            device_token=device_token,
            require_activated=require_activated,
            allow_unbound=allow_unbound,
        )

    async def device_operation_enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.store, "create_device_operation"):
            return {"success": False, "error": "device operation storage is unavailable"}
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        op_type = _normalize_device_op_type(payload.get("op_type") or payload.get("operation_type") or payload.get("type"))
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        if not op_type:
            return {"success": False, "error": "op_type is required"}
        command_type = _device_op_command_type(op_type)
        if not command_type:
            return {"success": False, "error": f"unsupported op_type: {op_type}"}
        operation_payload = payload.get("payload")
        if not isinstance(operation_payload, dict):
            return {"success": False, "error": "payload must be object"}
        operation_id = str(payload.get("operation_id") or payload.get("operationId") or "").strip()
        if not operation_id:
            operation_id = f"op-{secrets.token_hex(8)}"
        now = int(time.time() * 1000)
        self.store.create_device_operation(
            operation_id=operation_id,
            device_id=device_id,
            session_id=session_id,
            op_type=op_type,
            command_type=command_type,
            status="queued",
            payload=operation_payload,
            result={},
            error="",
            created_at_ms=now,
            updated_at_ms=now,
            acked_at_ms=0,
        )
        item = self.store.get_device_operation(operation_id=operation_id)
        return {"success": True, "operation": item}

    async def device_operation_mark(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.store, "update_device_operation"):
            return {"success": False, "error": "device operation storage is unavailable"}
        operation_id = str(payload.get("operation_id") or payload.get("operationId") or "").strip()
        if not operation_id:
            return {"success": False, "error": "operation_id is required"}
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"queued", "sent", "acked", "failed", "canceled"}:
            return {"success": False, "error": "invalid status"}
        result = payload.get("result")
        result_map = result if isinstance(result, dict) else {}
        error = str(payload.get("error") or "").strip()
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or None
        acked_at_raw = _to_int(payload.get("acked_at_ms"), default=0)
        acked_at: int | None = None
        if status == "acked":
            acked_at = int(acked_at_raw or int(time.time() * 1000))
        elif status in {"failed", "canceled"}:
            acked_at = int(acked_at_raw or 0)
        changed = self.store.update_device_operation(
            operation_id=operation_id,
            status=status,
            result=result_map,
            error=error,
            session_id=session_id,
            updated_at_ms=int(time.time() * 1000),
            acked_at_ms=acked_at,
        )
        if not changed:
            return {"success": False, "error": "operation not found"}
        item = self.store.get_device_operation(operation_id=operation_id)
        return {"success": True, "operation": item}

    async def device_operation_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.store, "list_device_operations"):
            return {"success": False, "error": "device operation storage is unavailable"}
        operation_id = str(payload.get("operation_id") or payload.get("operationId") or "").strip()
        if operation_id:
            item = self.store.get_device_operation(operation_id=operation_id)
            return {"success": True, "count": 1 if item else 0, "items": [item] if item else []}
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip() or None
        status = str(payload.get("status") or "").strip() or None
        op_type = (
            _normalize_device_op_type(payload.get("op_type") or payload.get("operation_type") or payload.get("type"))
            or None
        )
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)
        limit = _to_int(payload.get("limit"), default=100) or 100
        limit = min(max(1, limit), 1000)
        items = self.store.list_device_operations(
            device_id=device_id,
            status=status,
            op_type=op_type,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "filters": {
                "device_id": device_id,
                "status": status,
                "op_type": op_type,
                "limit": limit,
                "offset": offset,
            },
            "count": len(items),
            "items": items,
        }

    async def thought_trace_append(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.store, "add_thought_trace"):
            return {"success": False, "error": "thought trace storage is unavailable"}
        trace_id = str(payload.get("trace_id") or payload.get("traceId") or "").strip()
        if not trace_id:
            return {"success": False, "error": "trace_id is required"}
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        source = str(payload.get("source") or "manual").strip()
        stage = str(payload.get("stage") or "").strip()
        if not stage:
            return {"success": False, "error": "stage is required"}
        body = payload.get("payload")
        if not isinstance(body, dict):
            body = {}
        ts = _to_int(payload.get("ts"))
        trace_pk = self.store.add_thought_trace(
            trace_id=trace_id,
            session_id=session_id,
            source=source,
            stage=stage,
            payload=body,
            ts=ts,
        )
        return {
            "success": True,
            "trace": {
                "id": trace_pk,
                "trace_id": trace_id,
                "session_id": session_id,
                "source": source,
                "stage": stage,
                "payload": body,
                "ts": int(ts or int(time.time() * 1000)),
            },
        }

    async def thought_trace_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.store, "list_thought_traces"):
            return {"success": False, "error": "thought trace storage is unavailable"}
        trace_id = str(payload.get("trace_id") or payload.get("traceId") or "").strip() or None
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or None
        source = str(payload.get("source") or "").strip() or None
        stage = str(payload.get("stage") or "").strip() or None
        start_ts = _to_int(payload.get("start_ts"))
        end_ts = _to_int(payload.get("end_ts"))
        order = str(payload.get("order") or "asc").strip().lower()
        if order not in {"asc", "desc"}:
            order = "asc"
        offset = max(0, _to_int(payload.get("offset"), default=0) or 0)
        limit = _to_int(payload.get("limit"), default=200) or 200
        limit = min(max(1, limit), 5000)
        items = self.store.list_thought_traces(
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
        return {
            "success": True,
            "filters": {
                "trace_id": trace_id,
                "session_id": session_id,
                "source": source,
                "stage": stage,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "order": order,
                "limit": limit,
                "offset": offset,
            },
            "count": len(items),
            "items": items,
        }

    async def thought_trace_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(payload.get("trace_id") or payload.get("traceId") or "").strip()
        if not trace_id:
            return {"success": False, "error": "trace_id is required"}
        query_payload = dict(payload)
        query_payload["trace_id"] = trace_id
        query_payload["order"] = "asc"
        query_payload["offset"] = payload.get("offset", 0)
        query_payload["limit"] = payload.get("limit", 1000)
        result = await self.thought_trace_query(query_payload)
        if not result.get("success"):
            return result
        items = result.get("items")
        traces = items if isinstance(items, list) else []
        first_ts = int(traces[0]["ts"]) if traces else 0
        last_ts = int(traces[-1]["ts"]) if traces else 0
        sources: dict[str, int] = defaultdict(int)
        stages: dict[str, int] = defaultdict(int)
        for item in traces:
            if isinstance(item, dict):
                sources[str(item.get("source") or "")] += 1
                stages[str(item.get("stage") or "")] += 1
        steps: list[dict[str, Any]] = []
        for idx, item in enumerate(traces, start=1):
            data = item if isinstance(item, dict) else {}
            steps.append(
                {
                    "step": idx,
                    "ts": int(data.get("ts") or 0),
                    "source": str(data.get("source") or ""),
                    "stage": str(data.get("stage") or ""),
                    "payload": data.get("payload") if isinstance(data.get("payload"), dict) else {},
                }
            )
        return {
            "success": True,
            "trace_id": trace_id,
            "summary": {
                "count": len(traces),
                "first_ts": first_ts,
                "last_ts": last_ts,
                "duration_ms": max(0, last_ts - first_ts) if traces else 0,
                "sources": _sort_count_dict(sources),
                "stages": _sort_count_dict(stages),
            },
            "steps": steps,
            "items": traces,
        }

    def _ingest_queue_snapshot(self) -> dict[str, Any]:
        queue = self._ingest_queue
        depth = int(queue.qsize()) if queue is not None else 0
        max_size = int(self.ingest_queue_max_size)
        capacity = max(1, max_size)
        utilization = float(depth) / float(capacity)
        avg_latency = (
            float(self._ingest_latency_total_ms) / float(self._ingest_latency_samples)
            if self._ingest_latency_samples > 0
            else 0.0
        )
        return {
            "enabled": True,
            "started": bool(self._ingest_started),
            "shutdown": bool(self._ingest_shutdown),
            "policy": self.ingest_overflow_policy,
            "workers": int(self.ingest_workers),
            "max_size": max_size,
            "depth": depth,
            "utilization": round(utilization, 4),
            "in_flight": int(self._ingest_in_flight),
            "max_depth_seen": int(self._ingest_max_depth),
            "enqueued_total": int(self._ingest_enqueued_total),
            "processed_total": int(self._ingest_processed_total),
            "failed_total": int(self._ingest_failed_total),
            "rejected_total": int(self._ingest_rejected_total),
            "dropped_total": int(self._ingest_dropped_total),
            "avg_latency_ms": round(avg_latency, 2),
        }


def _to_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_trace_id(payload: dict[str, Any] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    trace = data.get("trace_id") or data.get("traceId")
    return str(trace or "").strip()


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_device_op_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    alias = {
        "set_config": "set_config",
        "config": "set_config",
        "tool_call": "tool_call",
        "tool": "tool_call",
        "ota_plan": "ota_plan",
        "ota": "ota_plan",
    }
    return alias.get(text, text)


def _device_op_command_type(op_type: str) -> str:
    mapping = {
        "set_config": "set_config",
        "tool_call": "tool_call",
        "ota_plan": "ota_plan",
    }
    return mapping.get(str(op_type or "").strip().lower(), "")


def _sort_count_dict(data: dict[str, int]) -> dict[str, int]:
    return dict(sorted(data.items(), key=lambda kv: (-int(kv[1]), kv[0])))


def _extract_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _extract_structured_context_from_event(item: dict[str, Any]) -> dict[str, Any] | None:
    payload = item.get("payload")
    payload_map = payload if isinstance(payload, dict) else {}
    context = payload_map.get("structured_context")
    return context if isinstance(context, dict) else None


def _structured_context_matches(
    context: dict[str, Any] | None,
    *,
    has_objects: bool | None,
    has_ocr: bool | None,
    has_risk_hints: bool | None,
    object_contains: str,
    ocr_contains: str,
    risk_hint_contains: str,
) -> bool:
    if context is None:
        return (
            has_objects is None
            and has_ocr is None
            and has_risk_hints is None
            and not object_contains
            and not ocr_contains
            and not risk_hint_contains
        )

    objects = context.get("objects")
    object_items = objects if isinstance(objects, list) else []
    ocr = context.get("ocr")
    ocr_items = ocr if isinstance(ocr, list) else []
    risk_hints = context.get("risk_hints")
    hint_items = risk_hints if isinstance(risk_hints, list) else []

    if has_objects is not None and bool(object_items) != bool(has_objects):
        return False
    if has_ocr is not None and bool(ocr_items) != bool(has_ocr):
        return False
    if has_risk_hints is not None and bool(hint_items) != bool(has_risk_hints):
        return False

    if object_contains:
        target = object_contains.lower()
        labels = []
        for item in object_items:
            if isinstance(item, dict):
                labels.append(str(item.get("label") or item.get("name") or "").strip().lower())
            else:
                labels.append(str(item or "").strip().lower())
        if not any(target in text for text in labels if text):
            return False

    if ocr_contains:
        target = ocr_contains.lower()
        texts = []
        for item in ocr_items:
            if isinstance(item, dict):
                texts.append(str(item.get("text") or "").strip().lower())
            else:
                texts.append(str(item or "").strip().lower())
        if not any(target in text for text in texts if text):
            return False

    if risk_hint_contains:
        target = risk_hint_contains.lower()
        texts = [str(item or "").strip().lower() for item in hint_items]
        if not any(target in text for text in texts if text):
            return False

    return True

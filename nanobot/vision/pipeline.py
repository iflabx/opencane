"""Multimodal image lifelog pipeline skeleton."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from nanobot.vision.dedup import compute_image_hash, is_near_duplicate
from nanobot.vision.image_assets import ImageAssetStore
from nanobot.vision.indexer import VisionIndexer
from nanobot.vision.store import VisionLifelogStore


def _now_ms() -> int:
    return int(time.time() * 1000)


class VisionLifelogPipeline:
    """Minimal end-to-end image ingestion pipeline for P2 scaffolding."""

    def __init__(
        self,
        *,
        store: VisionLifelogStore,
        indexer: VisionIndexer,
        analyzer: Any | None = None,
        asset_store: ImageAssetStore | None = None,
        dedup_max_distance: int = 3,
    ) -> None:
        self.store = store
        self.indexer = indexer
        self.analyzer = analyzer
        self.asset_store = asset_store
        self.dedup_max_distance = max(0, dedup_max_distance)

    async def ingest_image(
        self,
        *,
        session_id: str,
        image_base64: str,
        question: str = "",
        mime: str = "image/jpeg",
        metadata: dict[str, Any] | None = None,
        ts: int | None = None,
    ) -> dict[str, Any]:
        ts_ms = int(ts or _now_ms())
        meta = dict(metadata or {})

        image_bytes = base64.b64decode(image_base64)
        image_hash = compute_image_hash(image_bytes)
        recent_hashes = self.store.recent_hashes(session_id=session_id, limit=50)
        is_dedup = is_near_duplicate(
            image_hash,
            recent_hashes,
            max_distance=self.dedup_max_distance,
        )
        deleted_uris: list[str] = []
        if self.asset_store is not None:
            image_uri, deleted_uris = self.asset_store.persist(
                session_id=session_id,
                image_bytes=image_bytes,
                mime=mime,
                image_hash=image_hash,
                ts_ms=ts_ms,
            )
        else:
            image_uri = f"inline:{mime};hash={image_hash}"
        image_id = self.store.record_image(
            session_id=session_id,
            image_uri=image_uri,
            dhash=image_hash,
            is_dedup=is_dedup,
            ts=ts_ms,
        )
        if deleted_uris:
            self.store.mark_assets_deleted(image_uris=deleted_uris)

        analysis = {
            "summary": "deduplicated frame",
            "objects": [],
            "ocr": [],
            "risk_hints": [],
            "actionable_summary": "",
            "risk_level": str(meta.get("risk_level") or "P3"),
            "risk_score": _to_float(meta.get("risk_score"), default=0.0),
            "confidence": _to_float(meta.get("confidence"), default=0.0),
        }
        if not is_dedup:
            analysis = await self._analyze(
                image_base64=image_base64,
                image_bytes=image_bytes,
                question=question,
                mime=mime,
                defaults=analysis,
            )

        summary = str(analysis.get("summary") or "").strip() or "analysis pending"
        objects = _normalize_object_items(analysis.get("objects"))
        ocr = _normalize_ocr_items(analysis.get("ocr"))
        risk_hints = _normalize_string_items(analysis.get("risk_hints"))
        actionable_summary = str(analysis.get("actionable_summary") or "").strip()
        risk_level = str(analysis.get("risk_level") or "P3")
        risk_score = _to_float(analysis.get("risk_score"), default=0.0)
        confidence = _to_float(analysis.get("confidence"), default=0.0)

        object_terms = " ".join(_extract_object_terms(objects))
        ocr_terms = " ".join(_extract_ocr_terms(ocr))
        risk_hint_terms = " ".join(risk_hints)
        title = summary.split(".")[0][:80] if summary else "image context"
        self.store.record_context(
            image_id=image_id,
            semantic_title=title or "image context",
            semantic_summary=summary,
            objects=objects,
            ocr=ocr,
            risk_hints=risk_hints,
            actionable_summary=actionable_summary,
            risk_level=risk_level,
            risk_score=risk_score,
            ts=ts_ms,
        )
        self.indexer.add_context(
            image_id=image_id,
            title=title or "image context",
            summary=summary,
            metadata={
                "session_id": session_id,
                "ts": ts_ms,
                "image_id": image_id,
                "dedup": is_dedup,
                "risk_level": risk_level,
                "has_objects": 1 if objects else 0,
                "has_ocr": 1 if ocr else 0,
                "has_risk_hints": 1 if risk_hints else 0,
                "object_terms": object_terms[:240],
                "ocr_terms": ocr_terms[:240],
                "risk_hint_terms": risk_hint_terms[:240],
            },
        )
        structured_context = {
            "summary": summary,
            "actionable_summary": actionable_summary,
            "objects": objects,
            "ocr": ocr,
            "risk_hints": risk_hints,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "confidence": confidence,
        }
        self.store.record_event(
            session_id=session_id,
            event_type="image_ingested",
            payload={
                "image_id": image_id,
                "dedup": is_dedup,
                "summary": summary,
                "question": question,
                "image_uri": image_uri,
                "structured_context": structured_context,
            },
            risk_level=risk_level,
            confidence=confidence,
            ts=ts_ms,
        )
        return {
            "success": True,
            "session_id": session_id,
            "image_id": image_id,
            "dedup": is_dedup,
            "summary": summary,
            "structured_context": structured_context,
            "image_uri": image_uri,
            "ts": ts_ms,
        }

    async def _analyze(
        self,
        *,
        image_base64: str,
        image_bytes: bytes,
        question: str,
        mime: str,
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] | None = None
        if self.analyzer is None:
            return dict(defaults)

        if hasattr(self.analyzer, "analyze"):
            result = await self.analyzer.analyze(question=question or "describe scene", image=image_bytes, mime=mime)
            payload = self._extract_structured_payload(result)
            return self._merge_structured_payload(defaults, payload)

        if hasattr(self.analyzer, "analyze_payload"):
            payload = {
                "image_base64": image_base64,
                "question": question or "describe scene",
                "mime": mime,
            }
            result = await self.analyzer.analyze_payload(payload)
            extracted = self._extract_structured_payload(result)
            return self._merge_structured_payload(defaults, extracted)

        return dict(defaults)

    def _extract_structured_payload(self, raw: Any) -> dict[str, Any]:
        if hasattr(raw, "success") and hasattr(raw, "result"):
            if bool(getattr(raw, "success")):
                return self._extract_structured_payload(getattr(raw, "result"))
            return {"summary": str(getattr(raw, "error", "") or "analysis pending")}

        if isinstance(raw, dict):
            payload = dict(raw)
            text = str(payload.get("summary") or payload.get("result") or payload.get("text") or "").strip()
            parsed = _parse_json_object(text) if text else None
            if isinstance(parsed, dict):
                merged = dict(payload)
                merged.update(parsed)
                if "summary" not in merged and text:
                    merged["summary"] = text
                return merged
            if text and "summary" not in payload:
                payload["summary"] = text
            return payload

        if isinstance(raw, str):
            text = raw.strip()
            parsed = _parse_json_object(text)
            if isinstance(parsed, dict):
                return parsed
            return {"summary": text}

        return {"summary": str(raw or "").strip()}

    def _merge_structured_payload(
        self,
        defaults: dict[str, Any],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        output = dict(defaults)
        if not isinstance(payload, dict):
            return output

        summary = str(
            payload.get("summary")
            or payload.get("semantic_summary")
            or payload.get("result")
            or payload.get("text")
            or output.get("summary")
            or ""
        ).strip()
        if summary:
            output["summary"] = summary

        actionable_summary = str(
            payload.get("actionable_summary")
            or payload.get("action")
            or payload.get("guidance")
            or ""
        ).strip()
        if actionable_summary:
            output["actionable_summary"] = actionable_summary

        objects = payload.get("objects")
        if objects is None:
            objects = payload.get("detections")
        output["objects"] = _normalize_object_items(objects)

        ocr = payload.get("ocr")
        if ocr is None:
            ocr = payload.get("ocr_items")
        output["ocr"] = _normalize_ocr_items(ocr)

        risk_hints = payload.get("risk_hints")
        if risk_hints is None:
            risk_hints = payload.get("warnings")
        output["risk_hints"] = _normalize_string_items(risk_hints)

        risk_level = str(payload.get("risk_level") or payload.get("risk") or "").strip()
        if risk_level:
            output["risk_level"] = risk_level

        output["risk_score"] = _to_float(payload.get("risk_score"), default=_to_float(output.get("risk_score"), 0.0))
        output["confidence"] = _to_float(payload.get("confidence"), default=_to_float(output.get("confidence"), 0.0))
        return output


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    raw = text.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_string_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            output.append(text)
    return output


def _normalize_object_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [{"label": text}] if text else []
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or item.get("object") or "").strip()
            if not label:
                continue
            normalized: dict[str, Any] = {"label": label}
            conf = item.get("confidence")
            try:
                normalized["confidence"] = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                normalized["confidence"] = None
            if isinstance(item.get("bbox"), dict):
                normalized["bbox"] = dict(item["bbox"])
            if normalized.get("confidence") is None:
                normalized.pop("confidence", None)
            output.append(normalized)
            continue
        text = str(item or "").strip()
        if text:
            output.append({"label": text})
    return output


def _normalize_ocr_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [{"text": text}] if text else []
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("value") or "").strip()
            if not text:
                continue
            normalized: dict[str, Any] = {"text": text}
            if "confidence" in item:
                try:
                    normalized["confidence"] = float(item["confidence"])
                except (TypeError, ValueError):
                    pass
            output.append(normalized)
            continue
        text = str(item or "").strip()
        if text:
            output.append({"text": text})
    return output


def _extract_object_terms(objects: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for item in objects:
        label = str(item.get("label") or "").strip()
        if label:
            terms.append(label)
    return terms


def _extract_ocr_terms(items: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if text:
            terms.append(text)
    return terms

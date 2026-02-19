"""Managed image asset store for lifelog ingestion."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def _safe_segment(value: str, *, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    cleaned = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in text)
    cleaned = cleaned.strip("-_")
    return cleaned or fallback


def _ext_for_mime(mime: str) -> str:
    value = str(mime or "").strip().lower()
    if value in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if value == "image/png":
        return "png"
    if value == "image/webp":
        return "webp"
    if value == "image/heic":
        return "heic"
    if value == "image/heif":
        return "heif"
    return "bin"


class ImageAssetStore:
    """File-based image asset manager with size-bounded retention."""

    URI_PREFIX = "asset://"

    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_files: int = 5000,
        cleanup_interval: int = 100,
    ) -> None:
        self.root_dir = Path(root_dir).expanduser()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.max_files = max(1, int(max_files))
        self.cleanup_interval = max(1, int(cleanup_interval))
        self._writes_since_cleanup = 0

    def persist(
        self,
        *,
        session_id: str,
        image_bytes: bytes,
        mime: str,
        image_hash: str,
        ts_ms: int,
    ) -> tuple[str, list[str]]:
        session_key = _safe_segment(session_id, fallback="unknown-session")
        day = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc).strftime("%Y%m%d")
        ext = _ext_for_mime(mime)
        file_name = f"{int(ts_ms)}-{_safe_segment(image_hash, fallback='hash')[:24]}.{ext}"
        rel = Path(session_key) / day / file_name
        full = self.root_dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        if not full.exists():
            tmp = full.with_suffix(full.suffix + ".tmp")
            tmp.write_bytes(image_bytes)
            os.replace(tmp, full)
        deleted_uris: list[str] = []
        self._writes_since_cleanup += 1
        if self._writes_since_cleanup >= self.cleanup_interval:
            deleted_uris = self.cleanup()
            self._writes_since_cleanup = 0
        return f"{self.URI_PREFIX}{rel.as_posix()}", deleted_uris

    def resolve_uri(self, uri: str) -> Path | None:
        text = str(uri or "").strip()
        if not text.startswith(self.URI_PREFIX):
            return None
        rel = text[len(self.URI_PREFIX) :]
        return self.root_dir / rel

    def cleanup(self) -> list[str]:
        files = [p for p in self.root_dir.rglob("*") if p.is_file()]
        overflow = len(files) - self.max_files
        if overflow <= 0:
            return []
        files.sort(key=lambda p: (p.stat().st_mtime, p.as_posix()))
        deleted_uris: list[str] = []
        for path in files[:overflow]:
            try:
                path.unlink(missing_ok=True)
                rel = path.relative_to(self.root_dir).as_posix()
                deleted_uris.append(f"{self.URI_PREFIX}{rel}")
            except Exception:
                continue
        return deleted_uris

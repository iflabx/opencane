"""Shared SQLite tuning helpers for single-container production workloads."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

_VALID_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
_VALID_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}
_VALID_TEMP_STORE = {"DEFAULT", "FILE", "MEMORY"}


@dataclass(slots=True)
class SQLiteTuningOptions:
    """Balanced defaults for write-heavy runtime usage."""

    busy_timeout_ms: int = 5000
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    temp_store: str = "MEMORY"
    wal_autocheckpoint_pages: int = 1000


def apply_sqlite_tuning(
    conn: sqlite3.Connection,
    *,
    options: SQLiteTuningOptions | None = None,
) -> dict[str, Any]:
    """Apply safe tuning pragmas and return the applied values."""

    tuning = options or SQLiteTuningOptions()
    applied: dict[str, Any] = {}
    cur = conn.cursor()

    busy_timeout_ms = max(0, int(tuning.busy_timeout_ms))
    cur.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    applied["busy_timeout_ms"] = busy_timeout_ms

    journal_mode = _normalize_value(
        tuning.journal_mode,
        valid=_VALID_JOURNAL_MODES,
        fallback="WAL",
    )
    cur.execute(f"PRAGMA journal_mode = {journal_mode}")
    row = cur.fetchone()
    applied["journal_mode"] = str(row[0]).upper() if row and row[0] is not None else journal_mode

    synchronous = _normalize_value(
        tuning.synchronous,
        valid=_VALID_SYNCHRONOUS,
        fallback="NORMAL",
    )
    cur.execute(f"PRAGMA synchronous = {synchronous}")
    applied["synchronous"] = synchronous

    temp_store = _normalize_value(
        tuning.temp_store,
        valid=_VALID_TEMP_STORE,
        fallback="MEMORY",
    )
    cur.execute(f"PRAGMA temp_store = {temp_store}")
    applied["temp_store"] = temp_store

    wal_autocheckpoint = max(0, int(tuning.wal_autocheckpoint_pages))
    if applied["journal_mode"] == "WAL":
        cur.execute(f"PRAGMA wal_autocheckpoint = {wal_autocheckpoint}")
    applied["wal_autocheckpoint_pages"] = wal_autocheckpoint

    conn.commit()
    return applied


def _normalize_value(value: object, *, valid: set[str], fallback: str) -> str:
    text = str(value or "").strip().upper()
    if text in valid:
        return text
    return fallback

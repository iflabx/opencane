"""SQLite storage for runtime observability samples."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from opencane.storage.sqlite_tuning import SQLiteTuningOptions, apply_sqlite_tuning

_SCHEMA_VERSION = 1


class SQLiteObservabilityStore:
    """Thread-safe observability sample persistence."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_rows: int | None = None,
        trim_every: int = 100,
        tuning_options: SQLiteTuningOptions | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._tuning_applied = apply_sqlite_tuning(self._conn, options=tuning_options)
        self._max_rows = max_rows if (max_rows is not None and int(max_rows) > 0) else None
        self._trim_every = max(1, int(trim_every))
        self._writes_since_trim = 0
        self.init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            current = self._get_user_version(cur)
            if current < 1:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_observability_samples (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts INTEGER NOT NULL,
                      healthy INTEGER NOT NULL,
                      metrics_json TEXT NOT NULL,
                      thresholds_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runtime_observability_ts "
                    "ON runtime_observability_samples(ts)"
                )
                self._set_user_version(cur, 1)
            self._conn.commit()

    def add_sample(self, sample: dict[str, Any]) -> int:
        ts = int(sample.get("ts") or 0)
        healthy = 1 if bool(sample.get("healthy")) else 0
        metrics = sample.get("metrics")
        thresholds = sample.get("thresholds")
        metric_map = dict(metrics) if isinstance(metrics, dict) else {}
        threshold_map = dict(thresholds) if isinstance(thresholds, dict) else {}
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO runtime_observability_samples(ts, healthy, metrics_json, thresholds_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ts,
                    healthy,
                    json.dumps(metric_map, ensure_ascii=False),
                    json.dumps(threshold_map, ensure_ascii=False),
                ),
            )
            self._writes_since_trim += 1
            if self._max_rows is not None and self._writes_since_trim >= self._trim_every:
                self._trim_locked(cur)
                self._writes_since_trim = 0
            self._conn.commit()
            return int(cur.lastrowid)

    def trim(self) -> int:
        """Trim persisted rows to max_rows, returns deleted row count."""
        if self._max_rows is None:
            return 0
        with self._lock:
            cur = self._conn.cursor()
            deleted = self._trim_locked(cur)
            self._conn.commit()
            return deleted

    def list_samples(
        self,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if start_ts is not None:
            where.append("ts >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            where.append("ts <= ?")
            params.append(int(end_ts))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT ts, healthy, metrics_json, thresholds_json
            FROM runtime_observability_samples
            {where_sql}
            ORDER BY ts DESC, id DESC
            LIMIT ? OFFSET ?
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "ts": int(row["ts"]),
                    "healthy": bool(row["healthy"]),
                    "metrics": json.loads(str(row["metrics_json"] or "{}")),
                    "thresholds": json.loads(str(row["thresholds_json"] or "{}")),
                }
            )
        return output

    @staticmethod
    def _get_user_version(cur: sqlite3.Cursor) -> int:
        cur.execute("PRAGMA user_version")
        row = cur.fetchone()
        if not row:
            return 0
        return int(row[0])

    @staticmethod
    def _set_user_version(cur: sqlite3.Cursor, version: int) -> None:
        cur.execute(f"PRAGMA user_version = {max(0, int(version))}")

    @property
    def schema_version(self) -> int:
        return _SCHEMA_VERSION

    def _trim_locked(self, cur: sqlite3.Cursor) -> int:
        if self._max_rows is None:
            return 0
        keep = max(1, int(self._max_rows))
        cur.execute("SELECT COUNT(1) FROM runtime_observability_samples")
        row = cur.fetchone()
        total = int(row[0]) if row and row[0] is not None else 0
        if total <= keep:
            return 0
        cur.execute(
            """
            DELETE FROM runtime_observability_samples
            WHERE id NOT IN (
              SELECT id
              FROM runtime_observability_samples
              ORDER BY ts DESC, id DESC
              LIMIT ?
            )
            """,
            (keep,),
        )
        return int(cur.rowcount)

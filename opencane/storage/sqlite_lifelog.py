"""SQLite storage for lifelog events, images, and multimodal contexts."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from opencane.storage.sqlite_tuning import SQLiteTuningOptions, apply_sqlite_tuning


def _now_ms() -> int:
    return int(time.time() * 1000)


class SQLiteLifelogStore:
    """Small SQLite helper used by P2 lifelog pipeline skeleton."""

    SCHEMA_VERSION = 7

    def __init__(
        self,
        db_path: str | Path,
        *,
        tuning_options: SQLiteTuningOptions | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._tuning_applied = apply_sqlite_tuning(self._conn, options=tuning_options)
        self.init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            version = self._get_user_version(cur)
            if version < 1:
                self._migrate_to_v1(cur)
                version = 1
            if version < 2:
                self._migrate_to_v2(cur)
                version = 2
            if version < 3:
                self._migrate_to_v3(cur)
                version = 3
            if version < 4:
                self._migrate_to_v4(cur)
                version = 4
            if version < 5:
                self._migrate_to_v5(cur)
                version = 5
            if version < 6:
                self._migrate_to_v6(cur)
                version = 6
            if version < 7:
                self._migrate_to_v7(cur)
                version = 7
            if version != self.SCHEMA_VERSION:
                self._set_user_version(cur, self.SCHEMA_VERSION)
            self._conn.commit()

    @staticmethod
    def _get_user_version(cur: sqlite3.Cursor) -> int:
        cur.execute("PRAGMA user_version")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _set_user_version(cur: sqlite3.Cursor, version: int) -> None:
        cur.execute(f"PRAGMA user_version = {max(0, int(version))}")

    def _migrate_to_v1(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lifelog_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              ts INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              risk_level TEXT NOT NULL,
              confidence REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lifelog_images (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              image_uri TEXT NOT NULL,
              dhash TEXT NOT NULL,
              is_dedup INTEGER NOT NULL,
              ts INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lifelog_contexts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              image_id INTEGER NOT NULL,
              semantic_title TEXT NOT NULL,
              semantic_summary TEXT NOT NULL,
              objects_json TEXT NOT NULL,
              ocr_json TEXT NOT NULL,
              risk_hints_json TEXT NOT NULL,
              actionable_summary TEXT NOT NULL,
              risk_level TEXT NOT NULL,
              risk_score REAL NOT NULL,
              ts INTEGER NOT NULL,
              FOREIGN KEY(image_id) REFERENCES lifelog_images(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lifelog_images_session_ts ON lifelog_images(session_id, ts)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lifelog_events_session_ts ON lifelog_events(session_id, ts)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lifelog_contexts_image_id ON lifelog_contexts(image_id)"
        )
        self._set_user_version(cur, 1)

    def _migrate_to_v2(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(lifelog_contexts)")
        columns = {str(row["name"]) for row in cur.fetchall()}
        if "risk_hints_json" not in columns:
            cur.execute(
                "ALTER TABLE lifelog_contexts "
                "ADD COLUMN risk_hints_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "actionable_summary" not in columns:
            cur.execute(
                "ALTER TABLE lifelog_contexts "
                "ADD COLUMN actionable_summary TEXT NOT NULL DEFAULT ''"
            )
        self._set_user_version(cur, 2)

    def _migrate_to_v3(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              device_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              state TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL,
              last_seen_ms INTEGER NOT NULL,
              closed_at_ms INTEGER NOT NULL,
              close_reason TEXT NOT NULL,
              last_seq INTEGER NOT NULL,
              last_outbound_seq INTEGER NOT NULL,
              metadata_json TEXT NOT NULL,
              telemetry_json TEXT NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              UNIQUE(device_id, session_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_sessions_device_updated "
            "ON device_sessions(device_id, updated_at_ms DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_sessions_state_updated "
            "ON device_sessions(state, updated_at_ms DESC)"
        )
        self._set_user_version(cur, 3)

    def _migrate_to_v4(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              device_id TEXT NOT NULL UNIQUE,
              device_token TEXT NOT NULL,
              status TEXT NOT NULL,
              user_id TEXT NOT NULL,
              activated_at_ms INTEGER NOT NULL,
              revoked_at_ms INTEGER NOT NULL,
              revoke_reason TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_bindings_status_updated "
            "ON device_bindings(status, updated_at_ms DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_bindings_user_updated "
            "ON device_bindings(user_id, updated_at_ms DESC)"
        )
        self._set_user_version(cur, 4)

    def _migrate_to_v5(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_operations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              operation_id TEXT NOT NULL UNIQUE,
              device_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              op_type TEXT NOT NULL,
              command_type TEXT NOT NULL,
              status TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              result_json TEXT NOT NULL,
              error TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              acked_at_ms INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_ops_device_updated "
            "ON device_operations(device_id, updated_at_ms DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_ops_status_updated "
            "ON device_operations(status, updated_at_ms DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_ops_type_updated "
            "ON device_operations(op_type, updated_at_ms DESC)"
        )
        self._set_user_version(cur, 5)

    def _migrate_to_v6(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS thought_traces (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trace_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              source TEXT NOT NULL,
              stage TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              ts INTEGER NOT NULL,
              created_at_ms INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_thought_traces_trace_ts "
            "ON thought_traces(trace_id, ts ASC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_thought_traces_session_ts "
            "ON thought_traces(session_id, ts ASC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_thought_traces_source_ts "
            "ON thought_traces(source, ts ASC)"
        )
        self._set_user_version(cur, 6)

    def _migrate_to_v7(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_samples (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              device_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              sample_json TEXT NOT NULL,
              raw_json TEXT NOT NULL,
              trace_id TEXT NOT NULL,
              ts INTEGER NOT NULL,
              created_at_ms INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_samples_device_ts "
            "ON telemetry_samples(device_id, ts DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_samples_session_ts "
            "ON telemetry_samples(session_id, ts DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_samples_trace_ts "
            "ON telemetry_samples(trace_id, ts DESC)"
        )
        self._set_user_version(cur, 7)

    def add_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        risk_level: str = "P3",
        confidence: float = 0.0,
        ts: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO lifelog_events(session_id, event_type, ts, payload_json, risk_level, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    int(ts or _now_ms()),
                    json.dumps(payload, ensure_ascii=False),
                    risk_level,
                    float(confidence),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def add_image(
        self,
        *,
        session_id: str,
        image_uri: str,
        dhash: str,
        is_dedup: bool,
        ts: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO lifelog_images(session_id, image_uri, dhash, is_dedup, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    image_uri,
                    dhash,
                    1 if is_dedup else 0,
                    int(ts or _now_ms()),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def add_context(
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
        ts: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO lifelog_contexts(
                  image_id, semantic_title, semantic_summary,
                  objects_json, ocr_json, risk_hints_json, actionable_summary,
                  risk_level, risk_score, ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(image_id),
                    semantic_title,
                    semantic_summary,
                    json.dumps(objects or [], ensure_ascii=False),
                    json.dumps(ocr or [], ensure_ascii=False),
                    json.dumps(risk_hints or [], ensure_ascii=False),
                    str(actionable_summary or ""),
                    risk_level,
                    float(risk_score),
                    int(ts or _now_ms()),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_context_by_image_id(self, *, image_id: int) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT image_id, semantic_title, semantic_summary, objects_json, ocr_json,
                       risk_hints_json, actionable_summary, risk_level, risk_score, ts
                FROM lifelog_contexts
                WHERE image_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(image_id),),
            )
            row = cur.fetchone()
        return self._row_to_context(row)

    def get_contexts_by_image_ids(self, *, image_ids: list[int]) -> dict[int, dict[str, Any]]:
        normalized: list[int] = []
        for value in image_ids:
            try:
                image_id = int(value)
            except (TypeError, ValueError):
                continue
            if image_id > 0:
                normalized.append(image_id)
        normalized = sorted(set(normalized))
        if not normalized:
            return {}
        placeholders = ", ".join("?" for _ in normalized)
        sql = f"""
            SELECT image_id, semantic_title, semantic_summary, objects_json, ocr_json,
                   risk_hints_json, actionable_summary, risk_level, risk_score, ts
            FROM lifelog_contexts
            WHERE image_id IN ({placeholders})
            ORDER BY id DESC
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, normalized)
            rows = cur.fetchall()
        output: dict[int, dict[str, Any]] = {}
        for row in rows:
            image_id = int(row["image_id"])
            if image_id in output:
                continue
            context = self._row_to_context(row)
            if context:
                output[image_id] = context
        return output

    def recent_hashes(self, *, session_id: str, limit: int = 50) -> list[str]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT dhash
                FROM lifelog_images
                WHERE session_id = ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            )
            return [str(row["dhash"]) for row in cur.fetchall()]

    def mark_image_assets_deleted(self, *, image_uris: list[str]) -> int:
        uris = sorted({str(uri).strip() for uri in image_uris if str(uri).strip()})
        if not uris:
            return 0
        placeholders = ", ".join("?" for _ in uris)
        sql = f"""
            UPDATE lifelog_images
            SET image_uri = CASE
              WHEN image_uri LIKE 'deleted:%' THEN image_uri
              ELSE 'deleted:' || image_uri
            END
            WHERE image_uri IN ({placeholders})
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, uris)
            self._conn.commit()
            return int(cur.rowcount)

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
        params: list[Any] = [session_id]
        where = ["session_id = ?"]
        if start_ts is not None:
            where.append("ts >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            where.append("ts <= ?")
            params.append(int(end_ts))
        if event_type:
            where.append("event_type = ?")
            params.append(str(event_type))
        if risk_level:
            where.append("risk_level = ?")
            params.append(str(risk_level))
        params.append(max(1, int(limit)))
        params.append(max(0, int(offset)))
        sql = f"""
            SELECT id, session_id, event_type, ts, payload_json, risk_level, confidence
            FROM lifelog_events
            WHERE {" AND ".join(where)}
            ORDER BY ts DESC
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
                    "id": int(row["id"]),
                    "session_id": str(row["session_id"]),
                    "event_type": str(row["event_type"]),
                    "ts": int(row["ts"]),
                    "payload": json.loads(str(row["payload_json"])),
                    "risk_level": str(row["risk_level"]),
                    "confidence": float(row["confidence"]),
                }
            )
        return output

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
        now = int(updated_at_ms or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO device_sessions(
                  device_id, session_id, state, created_at_ms, last_seen_ms,
                  closed_at_ms, close_reason, last_seq, last_outbound_seq,
                  metadata_json, telemetry_json, updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, session_id) DO UPDATE SET
                  state = excluded.state,
                  last_seen_ms = excluded.last_seen_ms,
                  closed_at_ms = excluded.closed_at_ms,
                  close_reason = excluded.close_reason,
                  last_seq = excluded.last_seq,
                  last_outbound_seq = excluded.last_outbound_seq,
                  metadata_json = excluded.metadata_json,
                  telemetry_json = excluded.telemetry_json,
                  updated_at_ms = excluded.updated_at_ms
                """,
                (
                    str(device_id),
                    str(session_id),
                    str(state),
                    int(created_at_ms),
                    int(last_seen_ms),
                    int(closed_at_ms),
                    str(close_reason or ""),
                    int(last_seq),
                    int(last_outbound_seq),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    json.dumps(telemetry or {}, ensure_ascii=False),
                    now,
                ),
            )
            self._conn.commit()

    def close_device_session(
        self,
        *,
        device_id: str,
        session_id: str,
        reason: str = "",
        closed_at_ms: int | None = None,
    ) -> None:
        closed_ts = int(closed_at_ms or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE device_sessions
                SET state = 'closed',
                    closed_at_ms = ?,
                    close_reason = ?,
                    last_seen_ms = CASE WHEN last_seen_ms < ? THEN ? ELSE last_seen_ms END,
                    updated_at_ms = ?
                WHERE device_id = ? AND session_id = ?
                """,
                (
                    closed_ts,
                    str(reason or ""),
                    closed_ts,
                    closed_ts,
                    closed_ts,
                    str(device_id),
                    str(session_id),
                ),
            )
            if cur.rowcount <= 0:
                cur.execute(
                    """
                    INSERT INTO device_sessions(
                      device_id, session_id, state, created_at_ms, last_seen_ms,
                      closed_at_ms, close_reason, last_seq, last_outbound_seq,
                      metadata_json, telemetry_json, updated_at_ms
                    )
                    VALUES (?, ?, 'closed', ?, ?, ?, ?, -1, 0, '{}', '{}', ?)
                    """,
                    (
                        str(device_id),
                        str(session_id),
                        closed_ts,
                        closed_ts,
                        closed_ts,
                        str(reason or ""),
                        closed_ts,
                    ),
                )
            self._conn.commit()

    def list_device_sessions(
        self,
        *,
        device_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if device_id:
            where.append("device_id = ?")
            params.append(str(device_id))
        if state:
            where.append("state = ?")
            params.append(str(state))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT device_id, session_id, state, created_at_ms, last_seen_ms,
                   closed_at_ms, close_reason, last_seq, last_outbound_seq,
                   metadata_json, telemetry_json, updated_at_ms
            FROM device_sessions
            {where_sql}
            ORDER BY updated_at_ms DESC
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
                    "device_id": str(row["device_id"] or ""),
                    "session_id": str(row["session_id"] or ""),
                    "state": str(row["state"] or ""),
                    "created_at_ms": int(row["created_at_ms"] or 0),
                    "last_seen_ms": int(row["last_seen_ms"] or 0),
                    "closed_at_ms": int(row["closed_at_ms"] or 0),
                    "close_reason": str(row["close_reason"] or ""),
                    "last_seq": int(row["last_seq"] or -1),
                    "last_outbound_seq": int(row["last_outbound_seq"] or 0),
                    "metadata": self._json_load(row["metadata_json"], default={}),
                    "telemetry": self._json_load(row["telemetry_json"], default={}),
                    "updated_at_ms": int(row["updated_at_ms"] or 0),
                }
            )
        return output

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
        now = int(updated_at_ms or _now_ms())
        created = int(created_at_ms or now)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO device_bindings(
                  device_id, device_token, status, user_id, activated_at_ms,
                  revoked_at_ms, revoke_reason, metadata_json, created_at_ms, updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                  device_token = excluded.device_token,
                  status = excluded.status,
                  user_id = excluded.user_id,
                  activated_at_ms = excluded.activated_at_ms,
                  revoked_at_ms = excluded.revoked_at_ms,
                  revoke_reason = excluded.revoke_reason,
                  metadata_json = excluded.metadata_json,
                  updated_at_ms = excluded.updated_at_ms
                """,
                (
                    str(device_id),
                    str(device_token),
                    str(status),
                    str(user_id or ""),
                    int(activated_at_ms),
                    int(revoked_at_ms),
                    str(revoke_reason or ""),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created,
                    now,
                ),
            )
            self._conn.commit()

    def get_device_binding(self, *, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT device_id, device_token, status, user_id, activated_at_ms,
                       revoked_at_ms, revoke_reason, metadata_json, created_at_ms, updated_at_ms
                FROM device_bindings
                WHERE device_id = ?
                LIMIT 1
                """,
                (str(device_id),),
            )
            row = cur.fetchone()
        return self._row_to_device_binding(row)

    def list_device_bindings(
        self,
        *,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(str(status))
        if user_id:
            where.append("user_id = ?")
            params.append(str(user_id))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT device_id, device_token, status, user_id, activated_at_ms,
                   revoked_at_ms, revoke_reason, metadata_json, created_at_ms, updated_at_ms
            FROM device_bindings
            {where_sql}
            ORDER BY updated_at_ms DESC
            LIMIT ? OFFSET ?
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [item for row in rows if (item := self._row_to_device_binding(row))]

    def verify_device_binding(
        self,
        *,
        device_id: str,
        device_token: str,
        require_activated: bool = True,
        allow_unbound: bool = False,
    ) -> dict[str, Any]:
        item = self.get_device_binding(device_id=device_id)
        if item is None:
            return {"success": bool(allow_unbound), "reason": "device_not_registered", "binding": None}
        if str(item.get("device_token") or "") != str(device_token or ""):
            return {"success": False, "reason": "invalid_device_token", "binding": item}
        status = str(item.get("status") or "")
        if status == "revoked":
            return {"success": False, "reason": "device_revoked", "binding": item}
        if require_activated and status != "activated":
            return {"success": False, "reason": "device_not_activated", "binding": item}
        return {"success": True, "reason": "ok", "binding": item}

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
        now = int(updated_at_ms or _now_ms())
        created = int(created_at_ms or now)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO device_operations(
                  operation_id, device_id, session_id, op_type, command_type, status,
                  payload_json, result_json, error, created_at_ms, updated_at_ms, acked_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                  device_id = excluded.device_id,
                  session_id = excluded.session_id,
                  op_type = excluded.op_type,
                  command_type = excluded.command_type,
                  status = excluded.status,
                  payload_json = excluded.payload_json,
                  result_json = excluded.result_json,
                  error = excluded.error,
                  updated_at_ms = excluded.updated_at_ms,
                  acked_at_ms = excluded.acked_at_ms
                """,
                (
                    str(operation_id),
                    str(device_id),
                    str(session_id or ""),
                    str(op_type),
                    str(command_type),
                    str(status),
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    str(error or ""),
                    created,
                    now,
                    int(acked_at_ms),
                ),
            )
            self._conn.commit()

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
        now = int(updated_at_ms or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE device_operations
                SET status = ?,
                    result_json = ?,
                    error = ?,
                    session_id = CASE WHEN ? != '' THEN ? ELSE session_id END,
                    updated_at_ms = ?,
                    acked_at_ms = CASE WHEN ? IS NULL THEN acked_at_ms ELSE ? END
                WHERE operation_id = ?
                """,
                (
                    str(status),
                    json.dumps(result or {}, ensure_ascii=False),
                    str(error or ""),
                    str(session_id or ""),
                    str(session_id or ""),
                    now,
                    acked_at_ms,
                    int(acked_at_ms or 0) if acked_at_ms is not None else 0,
                    str(operation_id),
                ),
            )
            changed = cur.rowcount > 0
            self._conn.commit()
        return bool(changed)

    def get_device_operation(self, *, operation_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT operation_id, device_id, session_id, op_type, command_type, status,
                       payload_json, result_json, error, created_at_ms, updated_at_ms, acked_at_ms
                FROM device_operations
                WHERE operation_id = ?
                LIMIT 1
                """,
                (str(operation_id),),
            )
            row = cur.fetchone()
        return self._row_to_device_operation(row)

    def list_device_operations(
        self,
        *,
        device_id: str | None = None,
        status: str | None = None,
        op_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if device_id:
            where.append("device_id = ?")
            params.append(str(device_id))
        if status:
            where.append("status = ?")
            params.append(str(status))
        if op_type:
            where.append("op_type = ?")
            params.append(str(op_type))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT operation_id, device_id, session_id, op_type, command_type, status,
                   payload_json, result_json, error, created_at_ms, updated_at_ms, acked_at_ms
            FROM device_operations
            {where_sql}
            ORDER BY updated_at_ms DESC
            LIMIT ? OFFSET ?
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [item for row in rows if (item := self._row_to_device_operation(row))]

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
        now = int(ts or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO thought_traces(
                  trace_id, session_id, source, stage, payload_json, ts, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trace_id),
                    str(session_id or ""),
                    str(source or ""),
                    str(stage or ""),
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

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
        where: list[str] = []
        params: list[Any] = []
        if trace_id:
            where.append("trace_id = ?")
            params.append(str(trace_id))
        if session_id:
            where.append("session_id = ?")
            params.append(str(session_id))
        if source:
            where.append("source = ?")
            params.append(str(source))
        if stage:
            where.append("stage = ?")
            params.append(str(stage))
        if start_ts is not None:
            where.append("ts >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            where.append("ts <= ?")
            params.append(int(end_ts))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        order_token = "DESC" if str(order or "").strip().lower() == "desc" else "ASC"
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT id, trace_id, session_id, source, stage, payload_json, ts, created_at_ms
            FROM thought_traces
            {where_sql}
            ORDER BY ts {order_token}, id {order_token}
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
                    "id": int(row["id"] or 0),
                    "trace_id": str(row["trace_id"] or ""),
                    "session_id": str(row["session_id"] or ""),
                    "source": str(row["source"] or ""),
                    "stage": str(row["stage"] or ""),
                    "payload": self._json_load(row["payload_json"], default={}),
                    "ts": int(row["ts"] or 0),
                    "created_at_ms": int(row["created_at_ms"] or 0),
                }
            )
        return output

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
        now = int(ts or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO telemetry_samples(
                  device_id, session_id, schema_version, sample_json, raw_json, trace_id, ts, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(device_id or ""),
                    str(session_id or ""),
                    str(schema_version or ""),
                    json.dumps(sample or {}, ensure_ascii=False),
                    json.dumps(raw or {}, ensure_ascii=False),
                    str(trace_id or ""),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

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
        where: list[str] = []
        params: list[Any] = []
        if device_id:
            where.append("device_id = ?")
            params.append(str(device_id))
        if session_id:
            where.append("session_id = ?")
            params.append(str(session_id))
        if trace_id:
            where.append("trace_id = ?")
            params.append(str(trace_id))
        if start_ts is not None:
            where.append("ts >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            where.append("ts <= ?")
            params.append(int(end_ts))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        sql = f"""
            SELECT id, device_id, session_id, schema_version, sample_json, raw_json, trace_id, ts, created_at_ms
            FROM telemetry_samples
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
                    "id": int(row["id"] or 0),
                    "device_id": str(row["device_id"] or ""),
                    "session_id": str(row["session_id"] or ""),
                    "schema_version": str(row["schema_version"] or ""),
                    "sample": self._json_load(row["sample_json"], default={}),
                    "raw": self._json_load(row["raw_json"], default={}),
                    "trace_id": str(row["trace_id"] or ""),
                    "ts": int(row["ts"] or 0),
                    "created_at_ms": int(row["created_at_ms"] or 0),
                }
            )
        return output

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
        now = int(now_ms or _now_ms())
        cuts = {
            "runtime_events": _retention_cutoff_ms(runtime_events_days, now_ms=now),
            "thought_traces": _retention_cutoff_ms(thought_traces_days, now_ms=now),
            "device_sessions": _retention_cutoff_ms(device_sessions_days, now_ms=now),
            "device_operations": _retention_cutoff_ms(device_operations_days, now_ms=now),
            "telemetry_samples": _retention_cutoff_ms(telemetry_samples_days, now_ms=now),
        }
        deleted = {
            "runtime_events": 0,
            "thought_traces": 0,
            "device_sessions": 0,
            "device_operations": 0,
            "telemetry_samples": 0,
        }
        with self._lock:
            cur = self._conn.cursor()
            if cuts["runtime_events"] is not None:
                cur.execute(
                    "DELETE FROM lifelog_events WHERE ts < ?",
                    (int(cuts["runtime_events"]),),
                )
                deleted["runtime_events"] = int(cur.rowcount)
            if cuts["thought_traces"] is not None:
                cur.execute(
                    "DELETE FROM thought_traces WHERE ts < ?",
                    (int(cuts["thought_traces"]),),
                )
                deleted["thought_traces"] = int(cur.rowcount)
            if cuts["device_sessions"] is not None:
                cur.execute(
                    "DELETE FROM device_sessions WHERE state = 'closed' AND updated_at_ms < ?",
                    (int(cuts["device_sessions"]),),
                )
                deleted["device_sessions"] = int(cur.rowcount)
            if cuts["device_operations"] is not None:
                cur.execute(
                    "DELETE FROM device_operations WHERE updated_at_ms < ?",
                    (int(cuts["device_operations"]),),
                )
                deleted["device_operations"] = int(cur.rowcount)
            if cuts["telemetry_samples"] is not None:
                cur.execute(
                    "DELETE FROM telemetry_samples WHERE ts < ?",
                    (int(cuts["telemetry_samples"]),),
                )
                deleted["telemetry_samples"] = int(cur.rowcount)
            self._conn.commit()
        return deleted

    @staticmethod
    def _row_to_device_operation(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "operation_id": str(row["operation_id"] or ""),
            "device_id": str(row["device_id"] or ""),
            "session_id": str(row["session_id"] or ""),
            "op_type": str(row["op_type"] or ""),
            "command_type": str(row["command_type"] or ""),
            "status": str(row["status"] or ""),
            "payload": SQLiteLifelogStore._json_load(row["payload_json"], default={}),
            "result": SQLiteLifelogStore._json_load(row["result_json"], default={}),
            "error": str(row["error"] or ""),
            "created_at_ms": int(row["created_at_ms"] or 0),
            "updated_at_ms": int(row["updated_at_ms"] or 0),
            "acked_at_ms": int(row["acked_at_ms"] or 0),
        }

    @staticmethod
    def _row_to_device_binding(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "device_id": str(row["device_id"] or ""),
            "device_token": str(row["device_token"] or ""),
            "status": str(row["status"] or ""),
            "user_id": str(row["user_id"] or ""),
            "activated_at_ms": int(row["activated_at_ms"] or 0),
            "revoked_at_ms": int(row["revoked_at_ms"] or 0),
            "revoke_reason": str(row["revoke_reason"] or ""),
            "metadata": SQLiteLifelogStore._json_load(row["metadata_json"], default={}),
            "created_at_ms": int(row["created_at_ms"] or 0),
            "updated_at_ms": int(row["updated_at_ms"] or 0),
        }

    @staticmethod
    def _json_load(value: Any, *, default: Any) -> Any:
        if value is None:
            return default
        try:
            parsed = json.loads(str(value))
            return parsed
        except Exception:
            return default

    def _row_to_context(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "image_id": int(row["image_id"]),
            "semantic_title": str(row["semantic_title"] or ""),
            "semantic_summary": str(row["semantic_summary"] or ""),
            "objects": self._json_load(row["objects_json"], default=[]),
            "ocr": self._json_load(row["ocr_json"], default=[]),
            "risk_hints": self._json_load(row["risk_hints_json"], default=[]),
            "actionable_summary": str(row["actionable_summary"] or ""),
            "risk_level": str(row["risk_level"] or "P3"),
            "risk_score": float(row["risk_score"] or 0.0),
            "ts": int(row["ts"] or 0),
        }


def _retention_cutoff_ms(days: int | None, *, now_ms: int) -> int | None:
    if days is None:
        return None
    try:
        value = int(days)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return int(now_ms - value * 24 * 60 * 60 * 1000)

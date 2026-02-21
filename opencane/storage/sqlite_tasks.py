"""SQLite storage for digital task execution and push queue state."""

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


class SQLiteDigitalTaskStore:
    """Thread-safe SQLite helper for digital task persistence."""

    SCHEMA_VERSION = 3

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
            CREATE TABLE IF NOT EXISTS digital_tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL UNIQUE,
              session_id TEXT NOT NULL,
              goal TEXT NOT NULL,
              status TEXT NOT NULL,
              steps_json TEXT NOT NULL,
              result_json TEXT NOT NULL,
              error TEXT NOT NULL,
              timeout_seconds INTEGER NOT NULL,
              device_id TEXT NOT NULL,
              push_session_id TEXT NOT NULL,
              push_notify INTEGER NOT NULL,
              push_speak INTEGER NOT NULL,
              push_interrupt_previous INTEGER NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS digital_task_push_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              attempts INTEGER NOT NULL,
              next_retry_at INTEGER NOT NULL,
              last_error TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_digital_tasks_session_created "
            "ON digital_tasks(session_id, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_digital_tasks_status_updated "
            "ON digital_tasks(status, updated_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_digital_task_push_queue_lookup "
            "ON digital_task_push_queue(device_id, status, next_retry_at)"
        )
        self._set_user_version(cur, 1)

    def _migrate_to_v2(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(digital_tasks)")
        columns = {str(row["name"]) for row in cur.fetchall()}
        if "timeout_seconds" not in columns:
            cur.execute("ALTER TABLE digital_tasks ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 120")
        self._set_user_version(cur, 2)

    def _migrate_to_v3(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(digital_tasks)")
        columns = {str(row["name"]) for row in cur.fetchall()}
        if "device_id" not in columns:
            cur.execute("ALTER TABLE digital_tasks ADD COLUMN device_id TEXT NOT NULL DEFAULT ''")
        if "push_session_id" not in columns:
            cur.execute("ALTER TABLE digital_tasks ADD COLUMN push_session_id TEXT NOT NULL DEFAULT ''")
        if "push_notify" not in columns:
            cur.execute("ALTER TABLE digital_tasks ADD COLUMN push_notify INTEGER NOT NULL DEFAULT 0")
        if "push_speak" not in columns:
            cur.execute("ALTER TABLE digital_tasks ADD COLUMN push_speak INTEGER NOT NULL DEFAULT 1")
        if "push_interrupt_previous" not in columns:
            cur.execute(
                "ALTER TABLE digital_tasks ADD COLUMN push_interrupt_previous INTEGER NOT NULL DEFAULT 0"
            )
        self._set_user_version(cur, 3)

    def create_task(
        self,
        *,
        task_id: str,
        session_id: str,
        goal: str,
        status: str = "pending",
        steps: list[dict[str, Any]] | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
        timeout_seconds: int = 120,
        push_context: dict[str, Any] | None = None,
    ) -> None:
        now = _now_ms()
        context = dict(push_context or {})
        device_id = str(context.get("device_id") or "").strip()
        push_session_id = str(context.get("session_id") or session_id).strip()
        push_notify = 1 if bool(context.get("notify", bool(device_id))) else 0
        push_speak = 1 if bool(context.get("speak", True)) else 0
        push_interrupt_previous = 1 if bool(context.get("interrupt_previous", False)) else 0
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO digital_tasks(
                  task_id, session_id, goal, status, steps_json, result_json, error,
                  timeout_seconds, device_id, push_session_id, push_notify,
                  push_speak, push_interrupt_previous, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    session_id,
                    goal,
                    status,
                    json.dumps(steps or [], ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    max(1, int(timeout_seconds)),
                    device_id,
                    push_session_id,
                    push_notify,
                    push_speak,
                    push_interrupt_previous,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        return self.update_task_if_status(
            task_id,
            expected_statuses=None,
            status=status,
            steps=steps,
            result=result,
            error=error,
        )

    def update_task_if_status(
        self,
        task_id: str,
        *,
        expected_statuses: set[str] | None,
        status: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if steps is not None:
            updates.append("steps_json = ?")
            params.append(json.dumps(steps, ensure_ascii=False))
        if result is not None:
            updates.append("result_json = ?")
            params.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            updates.append("error = ?")
            params.append(str(error))
        updates.append("updated_at = ?")
        params.append(_now_ms())
        where = "task_id = ?"
        params.append(task_id)
        if expected_statuses:
            placeholders = ", ".join("?" for _ in expected_statuses)
            where += f" AND status IN ({placeholders})"
            params.extend(sorted(expected_statuses))
        sql = f"UPDATE digital_tasks SET {', '.join(updates)} WHERE {where}"
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
            return cur.rowcount > 0

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT task_id, session_id, goal, status, steps_json, result_json, error,
                       timeout_seconds, device_id, push_session_id, push_notify,
                       push_speak, push_interrupt_previous, created_at, updated_at
                FROM digital_tasks
                WHERE task_id = ?
                LIMIT 1
                """,
                (task_id,),
            )
            row = cur.fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if status:
            where.append("status = ?")
            params.append(status)
        limit = max(1, int(limit))
        offset = max(0, int(offset))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT task_id, session_id, goal, status, steps_json, result_json, error,
                   timeout_seconds, device_id, push_session_id, push_notify,
                   push_speak, push_interrupt_previous, created_at, updated_at
            FROM digital_tasks
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [task for row in rows if (task := self._row_to_task(row))]

    def list_unfinished_tasks(self, *, limit: int = 200) -> list[dict[str, Any]]:
        sql = """
            SELECT task_id, session_id, goal, status, steps_json, result_json, error,
                   timeout_seconds, device_id, push_session_id, push_notify,
                   push_speak, push_interrupt_previous, created_at, updated_at
            FROM digital_tasks
            WHERE status IN ('pending', 'running')
            ORDER BY created_at ASC
            LIMIT ?
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, (max(1, int(limit)),))
            rows = cur.fetchall()
        return [task for row in rows if (task := self._row_to_task(row))]

    def task_stats(self, *, session_id: str | None = None) -> dict[str, Any]:
        where_sql = ""
        params: list[Any] = []
        if session_id:
            where_sql = "WHERE session_id = ?"
            params.append(session_id)
        sql_counts = f"""
            SELECT status, COUNT(*) AS cnt
            FROM digital_tasks
            {where_sql}
            GROUP BY status
        """
        sql_duration = f"""
            SELECT AVG(updated_at - created_at) AS avg_ms
            FROM digital_tasks
            {where_sql}
            AND status IN ('success', 'failed', 'timeout', 'canceled')
        """ if where_sql else """
            SELECT AVG(updated_at - created_at) AS avg_ms
            FROM digital_tasks
            WHERE status IN ('success', 'failed', 'timeout', 'canceled')
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql_counts, params)
            rows = cur.fetchall()
            counts = {str(row["status"]): int(row["cnt"]) for row in rows}
            cur.execute(sql_duration, params)
            duration = cur.fetchone()
            if session_id:
                cur.execute(
                    """
                    SELECT steps_json
                    FROM digital_tasks
                    WHERE session_id = ? AND status IN ('success', 'failed', 'timeout', 'canceled')
                    """,
                    (session_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT steps_json
                    FROM digital_tasks
                    WHERE status IN ('success', 'failed', 'timeout', 'canceled')
                    """
                )
            step_rows = cur.fetchall()
        total = sum(counts.values())
        success = int(counts.get("success", 0))
        failed = int(counts.get("failed", 0))
        timeout = int(counts.get("timeout", 0))
        canceled = int(counts.get("canceled", 0))
        avg_ms = float(duration["avg_ms"]) if duration and duration["avg_ms"] is not None else 0.0
        success_rate = (success / total) if total > 0 else 0.0
        step_counts = [
            len(self._decode_json(row["steps_json"], []))
            for row in step_rows
        ]
        avg_step_count = (sum(step_counts) / len(step_counts)) if step_counts else 0.0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "timeout": timeout,
            "canceled": canceled,
            "pending": int(counts.get("pending", 0)),
            "running": int(counts.get("running", 0)),
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": round(avg_ms, 2),
            "avg_step_count": round(avg_step_count, 2),
            "counts_by_status": counts,
        }

    def enqueue_push_update(
        self,
        *,
        task_id: str,
        device_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> int:
        now = _now_ms()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO digital_task_push_queue(
                  task_id, device_id, session_id, payload_json, status,
                  attempts, next_retry_at, last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'pending', 0, ?, '', ?, ?)
                """,
                (
                    task_id,
                    device_id,
                    session_id,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_pending_push_updates(
        self,
        *,
        device_id: str,
        limit: int = 20,
        now_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        current = int(now_ms or _now_ms())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, task_id, device_id, session_id, payload_json, attempts, next_retry_at
                FROM digital_task_push_queue
                WHERE device_id = ? AND status = 'pending' AND next_retry_at <= ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (device_id, current, max(1, int(limit))),
            )
            rows = cur.fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "id": int(row["id"]),
                    "task_id": str(row["task_id"]),
                    "device_id": str(row["device_id"]),
                    "session_id": str(row["session_id"]),
                    "payload": self._decode_json(row["payload_json"], {}),
                    "attempts": int(row["attempts"]),
                    "next_retry_at": int(row["next_retry_at"]),
                }
            )
        return output

    def mark_push_update_sent(self, queue_id: int) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE digital_task_push_queue
                SET status = 'sent', updated_at = ?
                WHERE id = ?
                """,
                (_now_ms(), int(queue_id)),
            )
            self._conn.commit()

    def mark_push_update_retry(
        self,
        queue_id: int,
        *,
        error: str,
        retry_delay_ms: int,
    ) -> None:
        now = _now_ms()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE digital_task_push_queue
                SET attempts = attempts + 1,
                    next_retry_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now + max(0, int(retry_delay_ms)), str(error), now, int(queue_id)),
            )
            self._conn.commit()

    def list_push_queue(self, *, device_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if device_id:
            where.append("device_id = ?")
            params.append(device_id)
        if status:
            where.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT id, task_id, device_id, session_id, payload_json, status, attempts, next_retry_at, last_error
            FROM digital_task_push_queue
            {where_sql}
            ORDER BY id ASC
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
                    "task_id": str(row["task_id"]),
                    "device_id": str(row["device_id"]),
                    "session_id": str(row["session_id"]),
                    "payload": self._decode_json(row["payload_json"], {}),
                    "status": str(row["status"]),
                    "attempts": int(row["attempts"]),
                    "next_retry_at": int(row["next_retry_at"]),
                    "last_error": str(row["last_error"]),
                }
            )
        return output

    @staticmethod
    def _decode_json(raw: Any, default: Any) -> Any:
        try:
            return json.loads(str(raw))
        except Exception:
            return default

    def _row_to_task(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "task_id": str(row["task_id"]),
            "session_id": str(row["session_id"]),
            "goal": str(row["goal"]),
            "status": str(row["status"]),
            "steps": self._decode_json(row["steps_json"], []),
            "result": self._decode_json(row["result_json"], {}),
            "error": str(row["error"]),
            "timeout_seconds": int(row["timeout_seconds"]),
            "device_id": str(row["device_id"]),
            "push_context": {
                "device_id": str(row["device_id"]),
                "session_id": str(row["push_session_id"]),
                "notify": bool(row["push_notify"]),
                "speak": bool(row["push_speak"]),
                "interrupt_previous": bool(row["push_interrupt_previous"]),
            }
            if str(row["device_id"])
            else None,
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

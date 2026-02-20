import sqlite3

from nanobot.storage.sqlite_lifelog import SQLiteLifelogStore
from nanobot.storage.sqlite_observability import SQLiteObservabilityStore
from nanobot.storage.sqlite_tasks import SQLiteDigitalTaskStore


def test_sqlite_lifelog_store_sets_user_version(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog.db"
    store = SQLiteLifelogStore(db_path)
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA user_version")
        version = int(cur.fetchone()[0])
        conn.close()
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_structured_context_columns(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE lifelog_events (
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
        CREATE TABLE lifelog_images (
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
        CREATE TABLE lifelog_contexts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          image_id INTEGER NOT NULL,
          semantic_title TEXT NOT NULL,
          semantic_summary TEXT NOT NULL,
          objects_json TEXT NOT NULL,
          ocr_json TEXT NOT NULL,
          risk_level TEXT NOT NULL,
          risk_score REAL NOT NULL,
          ts INTEGER NOT NULL
        )
        """
    )
    cur.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(lifelog_contexts)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "risk_hints_json" in columns
        assert "actionable_summary" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_tasks_store_migrates_timeout_column(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "tasks.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE digital_tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL UNIQUE,
          session_id TEXT NOT NULL,
          goal TEXT NOT NULL,
          status TEXT NOT NULL,
          steps_json TEXT NOT NULL,
          result_json TEXT NOT NULL,
          error TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    cur.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    store = SQLiteDigitalTaskStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(digital_tasks)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "timeout_seconds" in columns
        assert "device_id" in columns
        assert "push_session_id" in columns
        assert "push_notify" in columns
        assert "push_speak" in columns
        assert "push_interrupt_previous" in columns
        assert version >= SQLiteDigitalTaskStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_observability_store_persists_samples(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "observability.db"
    store = SQLiteObservabilityStore(db_path)
    try:
        store.add_sample(
            {
                "ts": 1000,
                "healthy": True,
                "metrics": {"task_failure_rate": 0.1},
                "thresholds": {"task_failure_rate_max": 0.3},
            }
        )
        items = store.list_samples(start_ts=900, end_ts=2000, limit=10, offset=0)
        assert len(items) == 1
        assert items[0]["healthy"] is True
    finally:
        store.close()

    store2 = SQLiteObservabilityStore(db_path)
    try:
        items2 = store2.list_samples(start_ts=900, end_ts=2000, limit=10, offset=0)
        assert len(items2) == 1
        assert float(items2[0]["metrics"]["task_failure_rate"]) == 0.1
    finally:
        store2.close()


def test_sqlite_observability_store_trims_to_max_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "observability-trim.db"
    store = SQLiteObservabilityStore(db_path, max_rows=3, trim_every=1)
    try:
        for i in range(5):
            store.add_sample(
                {
                    "ts": 1000 + i,
                    "healthy": True,
                    "metrics": {"task_failure_rate": 0.1 * i},
                    "thresholds": {"task_failure_rate_max": 0.3},
                }
            )
        items = store.list_samples(start_ts=0, end_ts=9999, limit=10, offset=0)
        assert len(items) == 3
        assert [int(item["ts"]) for item in items] == [1004, 1003, 1002]
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_device_sessions_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate-v3.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE lifelog_events (
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
        CREATE TABLE lifelog_images (
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
        CREATE TABLE lifelog_contexts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          image_id INTEGER NOT NULL,
          semantic_title TEXT NOT NULL,
          semantic_summary TEXT NOT NULL,
          objects_json TEXT NOT NULL,
          ocr_json TEXT NOT NULL,
          risk_hints_json TEXT NOT NULL DEFAULT '[]',
          actionable_summary TEXT NOT NULL DEFAULT '',
          risk_level TEXT NOT NULL,
          risk_score REAL NOT NULL,
          ts INTEGER NOT NULL
        )
        """
    )
    cur.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(device_sessions)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "device_id" in columns
        assert "session_id" in columns
        assert "state" in columns
        assert "close_reason" in columns
        assert "metadata_json" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_device_session_crud(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-device-session.db"
    store = SQLiteLifelogStore(db_path)
    try:
        store.upsert_device_session(
            device_id="dev-1",
            session_id="sess-1",
            state="ready",
            created_at_ms=1000,
            last_seen_ms=1100,
            metadata={"firmware": "v1"},
            telemetry={"battery": 80},
        )
        store.upsert_device_session(
            device_id="dev-1",
            session_id="sess-1",
            state="listening",
            created_at_ms=1000,
            last_seen_ms=1200,
            metadata={"firmware": "v1"},
            telemetry={"battery": 79},
        )

        opened = store.list_device_sessions(device_id="dev-1", state="listening", limit=10, offset=0)
        assert len(opened) == 1
        assert opened[0]["session_id"] == "sess-1"
        assert opened[0]["telemetry"]["battery"] == 79

        store.close_device_session(device_id="dev-1", session_id="sess-1", reason="heartbeat_timeout", closed_at_ms=1300)
        closed = store.list_device_sessions(device_id="dev-1", state="closed", limit=10, offset=0)
        assert len(closed) == 1
        assert closed[0]["close_reason"] == "heartbeat_timeout"
        assert closed[0]["closed_at_ms"] == 1300
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_device_bindings_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate-v4.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE lifelog_events (
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
        CREATE TABLE lifelog_images (
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
        CREATE TABLE lifelog_contexts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          image_id INTEGER NOT NULL,
          semantic_title TEXT NOT NULL,
          semantic_summary TEXT NOT NULL,
          objects_json TEXT NOT NULL,
          ocr_json TEXT NOT NULL,
          risk_hints_json TEXT NOT NULL DEFAULT '[]',
          actionable_summary TEXT NOT NULL DEFAULT '',
          risk_level TEXT NOT NULL,
          risk_score REAL NOT NULL,
          ts INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE device_sessions (
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
    cur.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(device_bindings)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "device_id" in columns
        assert "device_token" in columns
        assert "status" in columns
        assert "user_id" in columns
        assert "revoke_reason" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_device_binding_crud_and_verify(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-device-binding.db"
    store = SQLiteLifelogStore(db_path)
    try:
        store.upsert_device_binding(
            device_id="dev-auth",
            device_token="token-1",
            status="registered",
            metadata={"hw": "ec600"},
            created_at_ms=1000,
            updated_at_ms=1000,
        )
        registered = store.get_device_binding(device_id="dev-auth")
        assert registered is not None
        assert registered["status"] == "registered"

        store.upsert_device_binding(
            device_id="dev-auth",
            device_token="token-1",
            status="activated",
            user_id="user-1",
            activated_at_ms=2000,
            metadata={"hw": "ec600"},
            created_at_ms=1000,
            updated_at_ms=2000,
        )
        active = store.get_device_binding(device_id="dev-auth")
        assert active is not None
        assert active["status"] == "activated"
        assert active["user_id"] == "user-1"

        ok = store.verify_device_binding(
            device_id="dev-auth",
            device_token="token-1",
            require_activated=True,
            allow_unbound=False,
        )
        assert ok["success"] is True

        bad_token = store.verify_device_binding(
            device_id="dev-auth",
            device_token="wrong",
            require_activated=True,
            allow_unbound=False,
        )
        assert bad_token["success"] is False
        assert bad_token["reason"] == "invalid_device_token"

        unbound = store.verify_device_binding(
            device_id="unknown",
            device_token="na",
            require_activated=True,
            allow_unbound=False,
        )
        assert unbound["success"] is False
        assert unbound["reason"] == "device_not_registered"

        allow = store.verify_device_binding(
            device_id="unknown",
            device_token="na",
            require_activated=True,
            allow_unbound=True,
        )
        assert allow["success"] is True
        assert allow["reason"] == "device_not_registered"
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_device_operations_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate-v5.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE lifelog_events (
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
        CREATE TABLE lifelog_images (
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
        CREATE TABLE lifelog_contexts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          image_id INTEGER NOT NULL,
          semantic_title TEXT NOT NULL,
          semantic_summary TEXT NOT NULL,
          objects_json TEXT NOT NULL,
          ocr_json TEXT NOT NULL,
          risk_hints_json TEXT NOT NULL DEFAULT '[]',
          actionable_summary TEXT NOT NULL DEFAULT '',
          risk_level TEXT NOT NULL,
          risk_score REAL NOT NULL,
          ts INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE device_sessions (
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
        """
        CREATE TABLE device_bindings (
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
    cur.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(device_operations)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "operation_id" in columns
        assert "device_id" in columns
        assert "op_type" in columns
        assert "command_type" in columns
        assert "status" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_device_operation_crud(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-device-operation.db"
    store = SQLiteLifelogStore(db_path)
    try:
        store.create_device_operation(
            operation_id="op-1",
            device_id="dev-1",
            session_id="sess-1",
            op_type="set_config",
            command_type="set_config",
            status="queued",
            payload={"volume": 5},
            result={},
            error="",
            created_at_ms=1000,
            updated_at_ms=1000,
            acked_at_ms=0,
        )
        created = store.get_device_operation(operation_id="op-1")
        assert created is not None
        assert created["status"] == "queued"
        assert created["payload"]["volume"] == 5

        changed = store.update_device_operation(
            operation_id="op-1",
            status="sent",
            result={"seq": 12},
            session_id="sess-2",
            updated_at_ms=1100,
        )
        assert changed is True
        sent = store.get_device_operation(operation_id="op-1")
        assert sent is not None
        assert sent["status"] == "sent"
        assert sent["session_id"] == "sess-2"
        assert sent["result"]["seq"] == 12

        store.update_device_operation(
            operation_id="op-1",
            status="acked",
            result={"device_ack": True},
            updated_at_ms=1200,
            acked_at_ms=1250,
        )
        acked = store.list_device_operations(device_id="dev-1", status="acked", limit=10, offset=0)
        assert len(acked) == 1
        assert acked[0]["operation_id"] == "op-1"
        assert acked[0]["acked_at_ms"] == 1250
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_thought_traces_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate-v6.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE lifelog_events (
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
        CREATE TABLE lifelog_images (
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
        CREATE TABLE lifelog_contexts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          image_id INTEGER NOT NULL,
          semantic_title TEXT NOT NULL,
          semantic_summary TEXT NOT NULL,
          objects_json TEXT NOT NULL,
          ocr_json TEXT NOT NULL,
          risk_hints_json TEXT NOT NULL DEFAULT '[]',
          actionable_summary TEXT NOT NULL DEFAULT '',
          risk_level TEXT NOT NULL,
          risk_score REAL NOT NULL,
          ts INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE device_sessions (
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
        """
        CREATE TABLE device_bindings (
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
        """
        CREATE TABLE device_operations (
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
    cur.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(thought_traces)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "trace_id" in columns
        assert "session_id" in columns
        assert "source" in columns
        assert "stage" in columns
        assert "payload_json" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_thought_trace_crud(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-thought-trace.db"
    store = SQLiteLifelogStore(db_path)
    try:
        store.add_thought_trace(
            trace_id="trace-1",
            session_id="sess-1",
            source="runtime:voice_turn",
            stage="voice_turn",
            payload={"text": "hello"},
            ts=1000,
        )
        store.add_thought_trace(
            trace_id="trace-1",
            session_id="sess-1",
            source="runtime:safety_policy",
            stage="safety_policy",
            payload={"downgraded": True},
            ts=1200,
        )
        store.add_thought_trace(
            trace_id="trace-2",
            session_id="sess-2",
            source="manual",
            stage="accepted",
            payload={"k": "v"},
            ts=1300,
        )

        asc = store.list_thought_traces(trace_id="trace-1", order="asc", limit=10, offset=0)
        assert len(asc) == 2
        assert asc[0]["ts"] == 1000
        assert asc[1]["ts"] == 1200
        assert asc[1]["payload"]["downgraded"] is True

        desc = store.list_thought_traces(session_id="sess-1", order="desc", limit=10, offset=0)
        assert len(desc) == 2
        assert desc[0]["ts"] == 1200
        assert desc[1]["ts"] == 1000

        filtered = store.list_thought_traces(
            source="manual",
            stage="accepted",
            start_ts=1200,
            end_ts=1500,
            limit=10,
            offset=0,
        )
        assert len(filtered) == 1
        assert filtered[0]["trace_id"] == "trace-2"
    finally:
        store.close()


def test_sqlite_lifelog_store_migrates_telemetry_samples_table(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-migrate-v7.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS thought_traces(id INTEGER PRIMARY KEY AUTOINCREMENT)")
    cur.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()

    store = SQLiteLifelogStore(db_path)
    try:
        conn2 = sqlite3.connect(str(db_path))
        cur2 = conn2.cursor()
        cur2.execute("PRAGMA table_info(telemetry_samples)")
        columns = {str(row[1]) for row in cur2.fetchall()}
        cur2.execute("PRAGMA user_version")
        version = int(cur2.fetchone()[0])
        conn2.close()
        assert "device_id" in columns
        assert "session_id" in columns
        assert "schema_version" in columns
        assert "sample_json" in columns
        assert "raw_json" in columns
        assert "trace_id" in columns
        assert version >= SQLiteLifelogStore.SCHEMA_VERSION
    finally:
        store.close()


def test_sqlite_lifelog_store_telemetry_samples_and_retention_cleanup(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "lifelog-telemetry-samples.db"
    store = SQLiteLifelogStore(db_path)
    try:
        store.add_telemetry_sample(
            device_id="dev-1",
            session_id="sess-1",
            schema_version="opencane.telemetry.v1",
            sample={"battery": {"percent": 80}},
            raw={"battery": 80},
            trace_id="trace-1",
            ts=1000,
        )
        store.add_telemetry_sample(
            device_id="dev-1",
            session_id="sess-1",
            schema_version="opencane.telemetry.v1",
            sample={"battery": {"percent": 90}},
            raw={"battery": 90},
            trace_id="trace-2",
            ts=2000,
        )
        items = store.list_telemetry_samples(device_id="dev-1", limit=10, offset=0)
        assert len(items) == 2
        assert items[0]["trace_id"] == "trace-2"
        assert items[1]["trace_id"] == "trace-1"

        deleted = store.cleanup_retention(
            telemetry_samples_days=1,
            now_ms=1_000_000_000,
        )
        assert int(deleted["telemetry_samples"]) >= 2
        remained = store.list_telemetry_samples(device_id="dev-1", limit=10, offset=0)
        assert remained == []
    finally:
        store.close()

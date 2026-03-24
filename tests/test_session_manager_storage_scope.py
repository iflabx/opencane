from __future__ import annotations

import json

from opencane.session.manager import Session, SessionManager


def test_session_manager_saves_sessions_under_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCANE_DATA_DIR", str(tmp_path / "legacy-data"))
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace)

    session = Session(key="cli:chat-a")
    session.add_message("user", "hello")
    manager.save(session)

    workspace_file = workspace / "sessions" / "cli_chat-a.jsonl"
    assert workspace_file.exists()
    assert not (tmp_path / "legacy-data" / "sessions" / "cli_chat-a.jsonl").exists()


def test_session_manager_migrates_legacy_session_to_workspace(tmp_path, monkeypatch) -> None:
    legacy_root = tmp_path / "legacy-data"
    monkeypatch.setenv("OPENCANE_DATA_DIR", str(legacy_root))
    legacy_sessions_dir = legacy_root / "sessions"
    legacy_sessions_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_sessions_dir / "cli_chat-b.jsonl"
    legacy_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "_type": "metadata",
                        "created_at": "2026-03-21T00:00:00",
                        "updated_at": "2026-03-21T00:00:00",
                        "metadata": {},
                        "last_consolidated": 0,
                    }
                ),
                json.dumps(
                    {
                        "role": "user",
                        "content": "legacy hello",
                        "timestamp": "2026-03-21T00:00:01",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace)
    session = manager.get_or_create("cli:chat-b")

    assert len(session.messages) == 1
    assert session.messages[0]["content"] == "legacy hello"
    assert (workspace / "sessions" / "cli_chat-b.jsonl").exists()
    assert not legacy_file.exists()


def test_list_sessions_uses_stored_session_key(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace)

    session = Session(key="cli:user_name_room")
    session.add_message("user", "hello")
    manager.save(session)

    listed = manager.list_sessions()
    assert listed
    assert listed[0]["key"] == "cli:user_name_room"


def test_list_sessions_legacy_filename_fallback_replaces_first_separator_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace)
    path = workspace / "sessions" / "cli_user_name_room.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_type": "metadata",
                "created_at": "2026-03-22T12:00:00",
                "updated_at": "2026-03-22T12:00:00",
                "metadata": {},
                "last_consolidated": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    listed = manager.list_sessions()
    assert listed
    assert listed[0]["key"] == "cli:user_name_room"

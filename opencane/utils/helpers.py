"""Utility functions for OpenCane runtime paths and helpers."""

import os
from datetime import datetime
from pathlib import Path

PRIMARY_DATA_DIR_NAME = ".opencane"
LEGACY_DATA_DIR_NAME = ".nanobot"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_primary_data_path() -> Path:
    """Return the preferred OpenCane data root."""
    return Path.home() / PRIMARY_DATA_DIR_NAME


def get_legacy_data_path() -> Path:
    """Return legacy nanobot data root."""
    return Path.home() / LEGACY_DATA_DIR_NAME


def get_data_path() -> Path:
    """
    Get the runtime data directory.

    Priority:
    1. `OPENCANE_DATA_DIR` env override
    2. Existing `~/.opencane`
    3. Existing legacy `~/.nanobot`
    4. Create and use `~/.opencane`
    """
    env_path = str(os.environ.get("OPENCANE_DATA_DIR") or "").strip()
    if env_path:
        return ensure_dir(Path(env_path).expanduser())

    primary = get_primary_data_path()
    if primary.exists():
        return ensure_dir(primary)

    legacy = get_legacy_data_path()
    if legacy.exists():
        return ensure_dir(legacy)

    return ensure_dir(primary)


def get_workspace_path(workspace: str | None = None) -> Path:
    """
    Get the workspace path.

    Args:
        workspace: Optional workspace path. Defaults to ~/.opencane/workspace
            (fallback to existing ~/.nanobot workspace if primary path missing).

    Returns:
        Expanded and ensured workspace path.
    """
    if workspace:
        path = Path(workspace).expanduser()
    else:
        path = get_data_path() / "workspace"
    return ensure_dir(path)


def get_sessions_path() -> Path:
    """Get the sessions storage directory."""
    return ensure_dir(get_data_path() / "sessions")


def get_skills_path(workspace: Path | None = None) -> Path:
    """Get the skills directory within the workspace."""
    ws = workspace or get_workspace_path()
    return ensure_dir(ws / "skills")


def timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().isoformat()


def truncate_string(s: str, max_len: int = 100, suffix: str = "...") -> str:
    """Truncate a string to max length, adding suffix if truncated."""
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix


def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Replace unsafe characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        name = name.replace(char, "_")
    return name.strip()


def parse_session_key(key: str) -> tuple[str, str]:
    """
    Parse a session key into channel and chat_id.

    Args:
        key: Session key in format "channel:chat_id"

    Returns:
        Tuple of (channel, chat_id)
    """
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid session key: {key}")
    return parts[0], parts[1]

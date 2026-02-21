"""Local backup/restore helpers for lifelog data."""

from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any


def create_lifelog_backup(
    *,
    archive_path: str | Path,
    sqlite_path: str | Path,
    image_asset_dir: str | Path | None = None,
) -> dict[str, Any]:
    sqlite_file = Path(sqlite_path).expanduser()
    if not sqlite_file.exists():
        raise FileNotFoundError(f"sqlite file not found: {sqlite_file}")
    archive = Path(archive_path).expanduser()
    archive.parent.mkdir(parents=True, exist_ok=True)
    images_dir = Path(image_asset_dir).expanduser() if image_asset_dir else None
    metadata = {
        "created_at_ms": int(time.time() * 1000),
        "sqlite": sqlite_file.name,
        "images_included": bool(images_dir and images_dir.exists()),
    }

    members: list[str] = []
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(sqlite_file, arcname="lifelog.db", recursive=False)
        members.append("lifelog.db")
        if images_dir and images_dir.exists():
            tar.add(images_dir, arcname="images", recursive=True)
            members.append("images/")
        meta_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="metadata.json")
        info.size = len(meta_bytes)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(meta_bytes))
        members.append("metadata.json")
    return {"archive_path": str(archive), "members": members}


def restore_lifelog_backup(
    *,
    archive_path: str | Path,
    destination_dir: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser()
    if not archive.exists():
        raise FileNotFoundError(f"archive not found: {archive}")
    dest = Path(destination_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    sqlite_target = dest / "lifelog.db"
    if sqlite_target.exists() and not overwrite:
        raise FileExistsError(f"destination already has lifelog.db: {sqlite_target}")

    restored: list[str] = []
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar.getmembers())
        tar.extractall(path=dest, members=members)
        restored = [m.name for m in members]
    return {"destination_dir": str(dest), "restored": restored}


def _safe_members(members: list[tarfile.TarInfo]) -> list[tarfile.TarInfo]:
    safe: list[tarfile.TarInfo] = []
    for member in members:
        name = str(member.name or "")
        path = Path(name)
        if path.is_absolute():
            continue
        if ".." in path.parts:
            continue
        safe.append(member)
    return safe

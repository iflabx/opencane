from __future__ import annotations

from pathlib import Path

import pytest

from opencane.storage.backup_bundle import create_lifelog_backup, restore_lifelog_backup


def test_lifelog_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    sqlite_file = tmp_path / "lifelog.db"
    sqlite_file.write_bytes(b"sqlite-binary")
    images_dir = tmp_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "a.jpg").write_bytes(b"img-a")

    archive = tmp_path / "backup" / "lifelog-backup.tar.gz"
    created = create_lifelog_backup(
        archive_path=archive,
        sqlite_path=sqlite_file,
        image_asset_dir=images_dir,
    )
    assert Path(created["archive_path"]).exists()
    assert "lifelog.db" in created["members"]

    restore_dir = tmp_path / "restore"
    restored = restore_lifelog_backup(
        archive_path=archive,
        destination_dir=restore_dir,
        overwrite=False,
    )
    assert "lifelog.db" in restored["restored"]
    assert (restore_dir / "lifelog.db").read_bytes() == b"sqlite-binary"
    assert (restore_dir / "images" / "a.jpg").read_bytes() == b"img-a"


def test_lifelog_restore_requires_overwrite_for_existing_db(tmp_path: Path) -> None:
    sqlite_file = tmp_path / "lifelog.db"
    sqlite_file.write_bytes(b"db")
    archive = tmp_path / "backup.tar.gz"
    create_lifelog_backup(archive_path=archive, sqlite_path=sqlite_file)

    restore_dir = tmp_path / "restore"
    restore_dir.mkdir(parents=True, exist_ok=True)
    (restore_dir / "lifelog.db").write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        restore_lifelog_backup(
            archive_path=archive,
            destination_dir=restore_dir,
            overwrite=False,
        )

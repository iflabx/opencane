#!/usr/bin/env python3
"""Create or restore local lifelog backup bundles."""

from __future__ import annotations

import argparse
import json
import sys

from nanobot.storage import create_lifelog_backup, restore_lifelog_backup


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifelog backup/restore helper")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="Create backup archive")
    backup.add_argument("--sqlite", required=True, help="Path to lifelog sqlite file")
    backup.add_argument("--images", default="", help="Path to lifelog image asset directory")
    backup.add_argument("--out", required=True, help="Output .tar.gz path")

    restore = sub.add_parser("restore", help="Restore backup archive")
    restore.add_argument("--archive", required=True, help="Backup archive path")
    restore.add_argument("--dest", required=True, help="Restore destination directory")
    restore.add_argument("--overwrite", action="store_true", help="Overwrite existing lifelog.db")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = create_lifelog_backup(
                archive_path=args.out,
                sqlite_path=args.sqlite,
                image_asset_dir=args.images or None,
            )
        else:
            result = restore_lifelog_backup(
                archive_path=args.archive,
                destination_dir=args.dest,
                overwrite=bool(args.overwrite),
            )
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

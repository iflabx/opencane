#!/usr/bin/env python3
"""Merge a deployment profile JSON into opencane config.json safely."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nanobot.config.loader import get_config_path
from nanobot.config.profile_merge import (
    backup_config_file,
    load_json_file,
    merge_profile_data,
    write_json_file,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge profile JSON into opencane config.json, validate it, and write canonical output."
        )
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="Profile JSON path (e.g. CONFIG_PROFILE_STAGING.json)",
    )
    parser.add_argument(
        "--config",
        default=str(get_config_path()),
        help="Target opencane config path (default: ~/.opencane/config.json)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backup when target config already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate merge and print summary only, without writing target file.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    profile_path = Path(args.profile).expanduser()
    config_path = Path(args.config).expanduser()

    if not profile_path.exists():
        print(f"profile not found: {profile_path}", file=sys.stderr)
        return 2

    try:
        existing_config = load_json_file(config_path) if config_path.exists() else {}
        profile_data = load_json_file(profile_path)
        merged_config = merge_profile_data(existing_config, profile_data)
    except json.JSONDecodeError as exc:
        print(f"invalid json: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"failed to merge profile: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("merge validation passed (dry-run)")
        print(f"profile: {profile_path}")
        print(f"target: {config_path}")
        print(f"top-level keys: {', '.join(sorted(merged_config.keys()))}")
        return 0

    backup_path: Path | None = None
    if config_path.exists() and not args.no_backup:
        backup_path = backup_config_file(config_path)

    write_json_file(config_path, merged_config)

    if backup_path is not None:
        print(f"backup created: {backup_path}")
    print(f"merged config written: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

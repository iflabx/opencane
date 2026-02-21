"""Helpers for merging deployment profile JSON into OpenCane config."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opencane.config.loader import convert_keys, convert_to_camel
from opencane.config.schema import Config


def deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dicts, with overlay values taking precedence."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = deep_merge_dicts(base_value, value)
        else:
            merged[key] = value
    return merged


def load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from file."""
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def normalize_config_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate config object and serialize into canonical camelCase output."""
    validated = Config.model_validate(convert_keys(data))
    return convert_to_camel(validated.model_dump())


def merge_profile_data(existing: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Merge existing config and profile, then validate and normalize result."""
    merged = deep_merge_dicts(existing, profile)
    return normalize_config_data(merged)


def backup_config_file(config_path: Path) -> Path:
    """Create timestamped backup for existing config file."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = config_path.with_name(f"{config_path.name}.bak.{ts}")
    shutil.copy2(config_path, backup_path)
    return backup_path


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    """Write JSON object to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def iter_paths(data: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Iterate all nested key/index paths in dict/list data."""
    paths: list[tuple[Any, ...]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            key_path = (*prefix, key)
            paths.append(key_path)
            paths.extend(iter_paths(value, key_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            idx_path = (*prefix, idx)
            paths.append(idx_path)
            paths.extend(iter_paths(item, idx_path))
    return paths


def path_exists(data: Any, path: tuple[Any, ...]) -> bool:
    """Check whether a nested path exists in dict/list data."""
    current = data
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return False
            current = current[part]
            continue
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def find_unknown_paths(source: dict[str, Any], normalized: dict[str, Any]) -> list[str]:
    """Find source paths dropped after schema normalization."""
    return [
        ".".join(str(p) for p in path)
        for path in iter_paths(source)
        if not path_exists(normalized, path)
    ]

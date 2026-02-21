import json
from pathlib import Path
from typing import Any

import pytest

from opencane.config.profile_merge import normalize_config_data

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILES = [
    REPO_ROOT / "CONFIG_PROFILE_DEV.json",
    REPO_ROOT / "CONFIG_PROFILE_STAGING.json",
    REPO_ROOT / "CONFIG_PROFILE_PROD.json",
]


def _iter_paths(data: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    paths: list[tuple[Any, ...]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            key_path = (*prefix, key)
            paths.append(key_path)
            paths.extend(_iter_paths(value, key_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            idx_path = (*prefix, idx)
            paths.append(idx_path)
            paths.extend(_iter_paths(item, idx_path))
    return paths


def _path_exists(data: Any, path: tuple[Any, ...]) -> bool:
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


@pytest.mark.parametrize("profile_path", PROFILE_FILES)
def test_profile_template_keys_are_known(profile_path: Path) -> None:
    profile = json.loads(profile_path.read_text())
    normalized = normalize_config_data(profile)

    missing_paths = [
        ".".join(str(p) for p in path)
        for path in _iter_paths(profile)
        if not _path_exists(normalized, path)
    ]
    assert not missing_paths, (
        "profile has unknown keys that are dropped during normalization: "
        + ", ".join(missing_paths)
    )

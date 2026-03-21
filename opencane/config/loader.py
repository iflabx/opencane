"""Configuration loading utilities."""

import json
from pathlib import Path
from typing import Any

from opencane.config.schema import Config
from opencane.utils.helpers import get_legacy_data_path, get_primary_data_path


def get_config_path() -> Path:
    """
    Resolve configuration path with backward compatibility.

    Preference:
    1. Existing `~/.opencane/config.json`
    2. Existing legacy `~/.opencane/config.json`
    3. New `~/.opencane/config.json`
    """
    primary = get_primary_data_path() / "config.json"
    legacy = get_legacy_data_path() / "config.json"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def get_primary_config_path() -> Path:
    """Get preferred write path for config."""
    return get_primary_data_path() / "config.json"


def get_data_dir() -> Path:
    """Get the OpenCane data directory."""
    from opencane.utils.helpers import get_data_path
    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(convert_keys(data))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_primary_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to camelCase format
    data = config.model_dump()
    data = convert_to_camel(data)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data


def convert_keys(data: Any, *, preserve_case: bool = False) -> Any:
    """Convert camelCase keys to snake_case for Pydantic."""
    if isinstance(data, dict):
        converted: dict[str, Any] = {}
        for key, value in data.items():
            source_key = str(key)
            target_key = source_key if preserve_case else camel_to_snake(source_key)
            child_preserve_case = preserve_case or target_key == "env"
            converted[target_key] = convert_keys(value, preserve_case=child_preserve_case)
        return converted
    if isinstance(data, list):
        return [convert_keys(item, preserve_case=preserve_case) for item in data]
    return data


def convert_to_camel(data: Any, *, preserve_case: bool = False) -> Any:
    """Convert snake_case keys to camelCase."""
    if isinstance(data, dict):
        converted: dict[str, Any] = {}
        for key, value in data.items():
            source_key = str(key)
            target_key = source_key if preserve_case else snake_to_camel(source_key)
            child_preserve_case = preserve_case or source_key == "env"
            converted[target_key] = convert_to_camel(value, preserve_case=child_preserve_case)
        return converted
    if isinstance(data, list):
        return [convert_to_camel(item, preserve_case=preserve_case) for item in data]
    return data


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])

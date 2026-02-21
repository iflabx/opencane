import json

import pytest

from opencane.config.profile_merge import (
    backup_config_file,
    deep_merge_dicts,
    merge_profile_data,
)


def test_deep_merge_dicts_nested() -> None:
    base = {
        "hardware": {
            "enabled": True,
            "mqtt": {
                "host": "old-broker",
                "port": 1883,
            },
        },
        "providers": {
            "openai": {
                "apiKey": "k1",
            }
        },
    }
    overlay = {
        "hardware": {
            "adapter": "ec600",
            "mqtt": {
                "host": "new-broker",
            },
        },
        "safety": {
            "lowConfidenceThreshold": 0.66,
        },
    }

    merged = deep_merge_dicts(base, overlay)
    assert merged["hardware"]["enabled"] is True
    assert merged["hardware"]["adapter"] == "ec600"
    assert merged["hardware"]["mqtt"]["host"] == "new-broker"
    assert merged["hardware"]["mqtt"]["port"] == 1883
    assert merged["providers"]["openai"]["apiKey"] == "k1"
    assert merged["safety"]["lowConfidenceThreshold"] == 0.66


def test_merge_profile_data_normalizes_and_validates() -> None:
    existing = {
        "hardware": {
            "enabled": True,
            "mqtt": {
                "port": 1883,
            },
        },
        "providers": {
            "openai": {
                "apiKey": "k1",
            }
        },
    }
    profile = {
        "hardware": {
            "adapter": "ec600",
            "mqtt": {
                "host": "127.0.0.1",
            },
        },
        "safety": {
            "lowConfidenceThreshold": 0.7,
        },
    }

    merged = merge_profile_data(existing, profile)

    assert merged["hardware"]["enabled"] is True
    assert merged["hardware"]["adapter"] == "ec600"
    assert merged["hardware"]["mqtt"]["host"] == "127.0.0.1"
    assert merged["hardware"]["mqtt"]["port"] == 1883
    assert merged["providers"]["openai"]["apiKey"] == "k1"
    assert merged["safety"]["lowConfidenceThreshold"] == 0.7


def test_merge_profile_data_raises_on_invalid_types() -> None:
    with pytest.raises(Exception):
        merge_profile_data(existing={}, profile={"hardware": {"port": "not-an-int"}})


def test_backup_config_file_creates_copy(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    source = {"hardware": {"enabled": True}}
    config_path.write_text(json.dumps(source))

    backup = backup_config_file(config_path)

    assert backup.exists()
    assert backup.read_text() == config_path.read_text()

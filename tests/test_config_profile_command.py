import json

from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_config_profile_apply_dry_run(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    config_path = tmp_path / "config.json"
    profile_path.write_text(
        json.dumps(
            {
                "hardware": {
                    "enabled": True,
                    "adapter": "ec600",
                }
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "config",
            "profile",
            "apply",
            "--profile",
            str(profile_path),
            "--config",
            str(config_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "dry-run" in result.stdout
    assert not config_path.exists()


def test_config_profile_apply_writes_and_backups(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    config_path = tmp_path / "config.json"
    profile_path.write_text(
        json.dumps(
            {
                "hardware": {
                    "adapter": "ec600",
                    "mqtt": {
                        "host": "broker-2",
                    },
                },
                "safety": {
                    "lowConfidenceThreshold": 0.7,
                },
            }
        )
    )
    config_path.write_text(
        json.dumps(
            {
                "hardware": {
                    "enabled": True,
                    "mqtt": {
                        "host": "broker-1",
                        "port": 1883,
                    },
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "config",
            "profile",
            "apply",
            "--profile",
            str(profile_path),
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "Merged config written" in result.stdout
    backup_files = list(tmp_path.glob("config.json.bak.*"))
    assert len(backup_files) == 1

    data = json.loads(config_path.read_text())
    assert data["hardware"]["enabled"] is True
    assert data["hardware"]["adapter"] == "ec600"
    assert data["hardware"]["mqtt"]["host"] == "broker-2"
    assert data["hardware"]["mqtt"]["port"] == 1883
    assert data["safety"]["lowConfidenceThreshold"] == 0.7


def test_config_profile_apply_missing_profile(tmp_path) -> None:
    config_path = tmp_path / "config.json"

    result = runner.invoke(
        app,
        [
            "config",
            "profile",
            "apply",
            "--profile",
            str(tmp_path / "missing.json"),
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 2
    assert "Profile not found" in result.stdout

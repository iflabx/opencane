import json

from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_config_check_passes_for_valid_config(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "hardware": {
                    "enabled": True,
                    "adapter": "ec600",
                },
                "lifelog": {
                    "enabled": True,
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "config",
            "check",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "Config validation passed" in result.stdout


def test_config_check_fails_when_missing(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "config",
            "check",
            "--config",
            str(tmp_path / "missing.json"),
        ],
    )

    assert result.exit_code == 2
    assert "Config file not found" in result.stdout


def test_config_check_strict_fails_unknown_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "hardware": {
                    "enabled": True,
                },
                "unknownRoot": {
                    "x": 1,
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "config",
            "check",
            "--config",
            str(config_path),
            "--strict",
        ],
    )

    assert result.exit_code == 1
    assert "Schema validation failed" in result.stdout

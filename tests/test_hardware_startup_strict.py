from typer.testing import CliRunner

from opencane.cli.commands import app
from opencane.config.schema import Config

runner = CliRunner()


class _DummyAgentLoop:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs

    async def close_mcp(self) -> None:
        return None


class _CaptureAgentLoop:
    last_kwargs = None

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        _CaptureAgentLoop.last_kwargs = dict(kwargs)

    async def close_mcp(self) -> None:
        return None


class _DummyBus:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs


class _DummySessionManager:
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs


def _build_config(tmp_path) -> Config:  # type: ignore[no-untyped-def]
    cfg = Config()
    cfg.hardware.enabled = True
    cfg.hardware.adapter = "mock"
    cfg.hardware.strict_startup = False
    cfg.hardware.observability_sqlite_path = str(tmp_path / "observability.db")
    cfg.vision.enabled = False
    cfg.lifelog.enabled = False
    cfg.digital_task.enabled = False
    cfg.providers.groq.api_key = ""
    cfg.providers.openai.api_key = ""
    cfg.providers.openai.api_base = None
    cfg.providers.custom.api_key = ""
    cfg.providers.custom.api_base = None
    return cfg


def test_hardware_serve_strict_startup_fails_without_stt(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = _build_config(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    monkeypatch.setattr("opencane.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("opencane.cli.commands._make_provider", lambda config: object())
    monkeypatch.setattr("opencane.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr("opencane.bus.queue.MessageBus", _DummyBus)
    monkeypatch.setattr("opencane.session.manager.SessionManager", _DummySessionManager)

    result = runner.invoke(app, ["hardware", "serve", "--strict-startup"])

    assert result.exit_code == 1
    assert "hardware strict startup failed" in result.stdout
    assert "No STT provider configured" in result.stdout


def test_hardware_serve_strict_startup_fails_server_audio_without_real_tts(
    monkeypatch,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    cfg = _build_config(tmp_path)
    cfg.hardware.tts_mode = "server_audio"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    monkeypatch.setattr("opencane.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("opencane.cli.commands._make_provider", lambda config: object())
    monkeypatch.setattr("opencane.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr("opencane.bus.queue.MessageBus", _DummyBus)
    monkeypatch.setattr("opencane.session.manager.SessionManager", _DummySessionManager)

    result = runner.invoke(app, ["hardware", "serve", "--strict-startup"])

    assert result.exit_code == 1
    assert "hardware strict startup failed" in result.stdout
    assert "tone fallback" in result.stdout


def test_hardware_serve_passes_max_subagents_from_config(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = _build_config(tmp_path)
    cfg.agents.defaults.max_subagents = 7
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    monkeypatch.setattr("opencane.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("opencane.cli.commands._make_provider", lambda config: object())
    monkeypatch.setattr("opencane.agent.loop.AgentLoop", _CaptureAgentLoop)
    monkeypatch.setattr("opencane.bus.queue.MessageBus", _DummyBus)
    monkeypatch.setattr("opencane.session.manager.SessionManager", _DummySessionManager)

    result = runner.invoke(app, ["hardware", "serve", "--strict-startup"])

    assert result.exit_code == 1
    assert isinstance(_CaptureAgentLoop.last_kwargs, dict)
    assert _CaptureAgentLoop.last_kwargs.get("max_subagents") == 7

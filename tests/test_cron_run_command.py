from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from opencane.bus.events import OutboundMessage
from opencane.cli.commands import app
from opencane.config.schema import Config

runner = CliRunner()


class _FakeAgentLoop:
    last_instance: "_FakeAgentLoop | None" = None

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del args
        self.kwargs = kwargs
        self.process_calls: list[dict[str, str]] = []
        self.closed = False
        _FakeAgentLoop.last_instance = self

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> OutboundMessage:
        del kwargs
        self.process_calls.append(
            {
                "content": content,
                "session_key": session_key,
                "channel": channel,
                "chat_id": chat_id,
            }
        )
        return OutboundMessage(channel=channel, chat_id=chat_id, content="agent-response")

    async def close_mcp(self) -> None:
        self.closed = True


class _FakeCronService:
    last_instance: "_FakeCronService | None" = None

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.on_job = None
        self.calls: list[tuple[str, bool]] = []
        _FakeCronService.last_instance = self

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        self.calls.append((job_id, force))
        if not self.on_job:
            return False
        job = SimpleNamespace(
            id=job_id,
            payload=SimpleNamespace(message="hello from job", channel="cli", to="chat-a"),
        )
        await self.on_job(job)
        return True


def test_cron_run_executes_agent_and_prints_result(tmp_path, monkeypatch) -> None:
    config = Config()
    printed: list[str] = []

    monkeypatch.setattr("opencane.config.loader.load_config", lambda: config)
    monkeypatch.setattr("opencane.config.loader.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("opencane.cli.commands._make_provider", lambda _cfg: object())
    monkeypatch.setattr("opencane.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("opencane.cron.service.CronService", _FakeCronService)
    monkeypatch.setattr(
        "opencane.safety.policy.SafetyPolicy.from_config",
        lambda _cfg: SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(
        "opencane.cli.commands._print_agent_response",
        lambda response, render_markdown=True: printed.append(str(response)),
    )

    result = runner.invoke(app, ["cron", "run", "job-1"])

    assert result.exit_code == 0
    assert "Job executed" in result.stdout
    assert _FakeCronService.last_instance is not None
    assert _FakeCronService.last_instance.calls == [("job-1", False)]
    assert _FakeAgentLoop.last_instance is not None
    assert _FakeAgentLoop.last_instance.process_calls == [
        {
            "content": "hello from job",
            "session_key": "cron:job-1",
            "channel": "cli",
            "chat_id": "chat-a",
        }
    ]
    assert _FakeAgentLoop.last_instance.closed is True
    assert printed == ["agent-response"]

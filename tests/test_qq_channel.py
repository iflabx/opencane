from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import opencane.channels.qq as qq_module
from opencane.bus.queue import MessageBus
from opencane.channels.qq import QQChannel, _make_bot_class
from opencane.config.schema import QQConfig


def _make_config() -> QQConfig:
    return QQConfig(enabled=True, app_id="app-id", secret="app-secret")


def test_make_bot_class_disables_file_handler_when_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, intents=None, ext_handlers=True):  # type: ignore[no-untyped-def]
            self.intents = intents
            self.ext_handlers = ext_handlers

    fake_botpy = SimpleNamespace(
        Client=_FakeClient,
        Intents=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(qq_module, "botpy", fake_botpy)

    channel = QQChannel(_make_config(), MessageBus())
    bot_class = _make_bot_class(channel)
    bot = bot_class()

    assert bot.ext_handlers is False


@pytest.mark.asyncio
async def test_start_is_long_running_and_awaits_run_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        async def start(self, appid: str, secret: str) -> None:
            del appid, secret
            return None

        async def close(self) -> None:
            return None

    monkeypatch.setattr(qq_module, "QQ_AVAILABLE", True)
    monkeypatch.setattr(qq_module, "_make_bot_class", lambda _channel: _FakeClient)

    channel = QQChannel(_make_config(), MessageBus())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _fake_run_bot() -> None:
        entered.set()
        await release.wait()

    monkeypatch.setattr(channel, "_run_bot", _fake_run_bot)

    task = asyncio.create_task(channel.start())
    await asyncio.wait_for(entered.wait(), timeout=0.2)
    assert task.done() is False

    channel._running = False
    release.set()
    await asyncio.wait_for(task, timeout=0.2)


@pytest.mark.asyncio
async def test_stop_closes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(qq_module, "QQ_AVAILABLE", True)
    channel = QQChannel(_make_config(), MessageBus())
    fake = _FakeClient()
    channel._client = fake  # type: ignore[assignment]
    channel._running = True

    await channel.stop()
    assert fake.closed is True

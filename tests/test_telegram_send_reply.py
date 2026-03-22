from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.error import TimedOut

from opencane.bus.events import OutboundMessage
from opencane.bus.queue import MessageBus
from opencane.channels.telegram import TelegramChannel
from opencane.config.schema import TelegramConfig


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.media_calls: list[dict] = []
        self.file = None

    async def send_message(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return None

    async def send_photo(self, **kwargs):  # type: ignore[no-untyped-def]
        self.media_calls.append({"kind": "photo", **kwargs})
        return None

    async def send_voice(self, **kwargs):  # type: ignore[no-untyped-def]
        self.media_calls.append({"kind": "voice", **kwargs})
        return None

    async def send_audio(self, **kwargs):  # type: ignore[no-untyped-def]
        self.media_calls.append({"kind": "audio", **kwargs})
        return None

    async def send_document(self, **kwargs):  # type: ignore[no-untyped-def]
        self.media_calls.append({"kind": "document", **kwargs})
        return None

    async def get_file(self, _file_id):  # type: ignore[no-untyped-def]
        return self.file


class _FakeApp:
    def __init__(self, bot: _FakeBot) -> None:
        self.bot = bot


class _FakeHTTPXRequest:
    instances: list["_FakeHTTPXRequest"] = []

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    @classmethod
    def clear(cls) -> None:
        cls.instances.clear()


class _FakeUpdater:
    def __init__(self, on_start_polling) -> None:  # type: ignore[no-untyped-def]
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del kwargs
        self._on_start_polling()


class _FakeStartBot:
    def __init__(self) -> None:
        self.commands = []

    async def get_me(self):
        return SimpleNamespace(id=999, username="opencane_test")

    async def set_my_commands(self, commands) -> None:  # type: ignore[no-untyped-def]
        self.commands = list(commands)
        return None


class _FakeStartApp:
    def __init__(self, on_start_polling) -> None:  # type: ignore[no-untyped-def]
        self.bot = _FakeStartBot()
        self.updater = _FakeUpdater(on_start_polling)

    def add_error_handler(self, _handler) -> None:  # type: ignore[no-untyped-def]
        return None

    def add_handler(self, _handler) -> None:  # type: ignore[no-untyped-def]
        return None

    async def initialize(self) -> None:
        return None

    async def start(self) -> None:
        return None


class _FakeBuilder:
    def __init__(self, app: _FakeStartApp) -> None:
        self.app = app
        self.request_value = None
        self.get_updates_request_value = None

    def token(self, _token: str):
        return self

    def request(self, request):  # type: ignore[no-untyped-def]
        self.request_value = request
        return self

    def get_updates_request(self, request):  # type: ignore[no-untyped-def]
        self.get_updates_request_value = request
        return self

    def build(self):
        return self.app


@pytest.mark.asyncio
async def test_telegram_send_uses_reply_when_enabled() -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=True),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"message_id": 456},
        )
    )

    assert len(bot.calls) == 1
    assert bot.calls[0]["reply_to_message_id"] == 456
    assert bot.calls[0]["allow_sending_without_reply"] is True


@pytest.mark.asyncio
async def test_telegram_forward_command_uses_username_sender_id() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    captured: dict = {}

    async def _capture_handle_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    channel._handle_message = _capture_handle_message  # type: ignore[assignment]
    update = SimpleNamespace(
        message=SimpleNamespace(chat_id=123, text="/new"),
        effective_user=SimpleNamespace(id=42, username="alice"),
    )

    await channel._forward_command(update, None)  # type: ignore[arg-type]

    assert captured["sender_id"] == "42|alice"
    assert captured["chat_id"] == "123"
    assert captured["content"] == "/new"


@pytest.mark.asyncio
async def test_telegram_forward_command_without_username_uses_numeric_sender_id() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    captured: dict = {}

    async def _capture_handle_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    channel._handle_message = _capture_handle_message  # type: ignore[assignment]
    update = SimpleNamespace(
        message=SimpleNamespace(chat_id=123, text="/help"),
        effective_user=SimpleNamespace(id=84, username=None),
    )

    await channel._forward_command(update, None)  # type: ignore[arg-type]

    assert captured["sender_id"] == "84"


@pytest.mark.asyncio
async def test_telegram_forward_status_command() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    captured: dict = {}

    async def _capture_handle_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    channel._handle_message = _capture_handle_message  # type: ignore[assignment]
    update = SimpleNamespace(
        message=SimpleNamespace(chat_id=123, text="/status"),
        effective_user=SimpleNamespace(id=99, username="bob"),
    )

    await channel._forward_command(update, None)  # type: ignore[arg-type]

    assert captured["sender_id"] == "99|bob"
    assert captured["content"] == "/status"


@pytest.mark.asyncio
async def test_telegram_send_skips_reply_when_disabled() -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"message_id": 456},
        )
    )

    assert len(bot.calls) == 1
    assert "reply_to_message_id" not in bot.calls[0]
    assert "allow_sending_without_reply" not in bot.calls[0]


@pytest.mark.asyncio
async def test_telegram_start_uses_separate_httpx_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeHTTPXRequest.clear()
    config = TelegramConfig(
        enabled=True,
        token="123:abc",
        allow_from=["*"],
        proxy="http://127.0.0.1:7890",
        connection_pool_size=40,
        pool_timeout=9.0,
    )
    channel = TelegramChannel(config=config, bus=MessageBus())
    app = _FakeStartApp(lambda: setattr(channel, "_running", False))
    builder = _FakeBuilder(app)

    monkeypatch.setattr("opencane.channels.telegram.HTTPXRequest", _FakeHTTPXRequest)
    monkeypatch.setattr(
        "opencane.channels.telegram.Application",
        SimpleNamespace(builder=lambda: builder),
    )

    await channel.start()

    assert len(_FakeHTTPXRequest.instances) == 2
    api_req, poll_req = _FakeHTTPXRequest.instances
    assert api_req.kwargs["proxy"] == config.proxy
    assert poll_req.kwargs["proxy"] == config.proxy
    assert api_req.kwargs["connection_pool_size"] == config.connection_pool_size
    assert poll_req.kwargs["connection_pool_size"] == 4
    assert api_req.kwargs["pool_timeout"] == config.pool_timeout
    assert poll_req.kwargs["pool_timeout"] == config.pool_timeout
    assert builder.request_value is api_req
    assert builder.get_updates_request_value is poll_req
    assert any(cmd.command == "status" for cmd in app.bot.commands)


@pytest.mark.asyncio
async def test_telegram_send_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]

    call_count = 0
    original_send = bot.send_message

    async def flaky_send(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise TimedOut()
        return await original_send(**kwargs)

    bot.send_message = flaky_send  # type: ignore[assignment]
    monkeypatch.setattr("opencane.channels.telegram._SEND_RETRY_BASE_DELAY", 0.01)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
        )
    )

    assert call_count == 3
    assert len(bot.calls) == 1


@pytest.mark.asyncio
async def test_telegram_send_remote_media_url_after_security_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]
    monkeypatch.setattr(
        "opencane.channels.telegram.validate_url_target",
        lambda url: (True, "") if url == "https://example.com/cat.jpg" else (False, "blocked"),
    )

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="",
            media=["https://example.com/cat.jpg"],
        )
    )

    assert bot.media_calls == [
        {
            "kind": "photo",
            "chat_id": 123,
            "photo": "https://example.com/cat.jpg",
        }
    ]
    assert bot.calls == []


@pytest.mark.asyncio
async def test_telegram_send_blocks_unsafe_remote_media_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]
    monkeypatch.setattr(
        "opencane.channels.telegram.validate_url_target",
        lambda _: (False, "Blocked: private/internal"),
    )

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="",
            media=["http://example.com/internal.jpg"],
        )
    )

    assert bot.media_calls == []
    assert bot.calls == [
        {
            "chat_id": 123,
            "text": "[Failed to send: internal.jpg]",
        }
    ]


def test_telegram_get_extension_uses_filename_fallback_for_generic_files() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )

    assert channel._get_extension("file", None, "report.final.v2.pdf") == ".pdf"


def test_telegram_get_extension_prefers_known_mime_type() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False),
        bus=MessageBus(),
    )

    assert channel._get_extension("file", "audio/ogg", "voice.mp3") == ".ogg"


def test_telegram_is_allowed_accepts_legacy_id_or_username_allowlist() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False, allow_from=["12345", "alice", "67890|bob"]),
        bus=MessageBus(),
    )

    assert channel.is_allowed("12345|carol") is True
    assert channel.is_allowed("99999|alice") is True
    assert channel.is_allowed("67890|bob") is True


def test_telegram_is_allowed_rejects_invalid_legacy_sender_shapes() -> None:
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False, allow_from=["alice"]),
        bus=MessageBus(),
    )

    assert channel.is_allowed("attacker|alice|extra") is False
    assert channel.is_allowed("not-a-number|alice") is False


@pytest.mark.asyncio
async def test_telegram_on_message_uses_file_unique_id_for_media_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    bot = _FakeBot()
    channel = TelegramChannel(
        config=TelegramConfig(enabled=True, reply_to_message=False, allow_from=["*"]),
        bus=MessageBus(),
    )
    channel._app = _FakeApp(bot)  # type: ignore[assignment]

    downloaded: dict[str, str] = {}

    class _FakeDownloadedFile:
        async def download_to_drive(self, path: str) -> None:
            downloaded["path"] = path

    bot.file = _FakeDownloadedFile()
    monkeypatch.setattr("opencane.channels.telegram.get_data_path", lambda: tmp_path)

    captured: dict = {}

    async def _capture_handle_message(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture_handle_message)
    monkeypatch.setattr(channel, "_start_typing", lambda _chat_id: None)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123, username="alice", first_name="Alice"),
        message=SimpleNamespace(
            message_id=1,
            chat_id=456,
            chat=SimpleNamespace(type="private"),
            text=None,
            caption=None,
            photo=[
                SimpleNamespace(
                    file_id="file-id-that-should-not-be-used",
                    file_unique_id="stable-unique-id",
                    mime_type="image/jpeg",
                    file_name=None,
                )
            ],
            voice=None,
            audio=None,
            document=None,
        ),
    )

    await channel._on_message(update, None)  # type: ignore[arg-type]

    assert downloaded["path"].endswith("stable-unique-id.jpg")
    assert captured["media"] == [str(tmp_path / "media" / "stable-unique-id.jpg")]

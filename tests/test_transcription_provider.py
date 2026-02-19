import pytest

from nanobot.providers.transcription import GroqTranscriptionProvider, OpenAITranscriptionProvider


@pytest.mark.asyncio
async def test_transcribe_bytes_without_api_key_returns_empty() -> None:
    provider = GroqTranscriptionProvider(api_key="")
    text = await provider.transcribe_bytes(b"dummy-audio")
    assert text == ""


@pytest.mark.asyncio
async def test_transcribe_bytes_calls_groq_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": "hello transcript"}

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, files, timeout):  # type: ignore[no-untyped-def]
            self.calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "files": files,
                    "timeout": timeout,
                }
            )
            return DummyResponse()

    holder: dict[str, DummyClient] = {}

    def fake_async_client():
        client = DummyClient()
        holder["client"] = client
        return client

    monkeypatch.setattr("nanobot.providers.transcription.httpx.AsyncClient", fake_async_client)

    provider = GroqTranscriptionProvider(api_key="test-key")
    text = await provider.transcribe_bytes(
        b"OggS...",
        filename="audio.ogg",
        content_type="audio/ogg",
    )

    assert text == "hello transcript"
    client = holder["client"]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["files"]["model"] == (None, "whisper-large-v3")


@pytest.mark.asyncio
async def test_openai_transcription_provider_uses_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": "openai transcript"}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, files, timeout):  # type: ignore[no-untyped-def]
            del headers, files, timeout
            assert url == "https://openai.example.com/v1/audio/transcriptions"
            return DummyResponse()

    monkeypatch.setattr("nanobot.providers.transcription.httpx.AsyncClient", lambda: DummyClient())
    provider = OpenAITranscriptionProvider(
        api_key="openai-key",
        api_base="https://openai.example.com",
        model="whisper-1",
    )
    text = await provider.transcribe_bytes(b"RIFF....", filename="audio.wav", content_type="audio/wav")
    assert text == "openai transcript"


@pytest.mark.asyncio
async def test_transcription_provider_supports_extra_headers_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": "header-only transcript"}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, files, timeout):  # type: ignore[no-untyped-def]
            assert url == "https://openai.example.com/v1/audio/transcriptions"
            assert headers.get("X-App-Code") == "app-code"
            assert "Authorization" not in headers
            del files, timeout
            return DummyResponse()

    monkeypatch.setattr("nanobot.providers.transcription.httpx.AsyncClient", lambda: DummyClient())
    provider = OpenAITranscriptionProvider(
        api_key="",
        api_base="https://openai.example.com",
        extra_headers={"X-App-Code": "app-code"},
    )
    text = await provider.transcribe_bytes(b"OggS....", filename="audio.ogg", content_type="audio/ogg")
    assert text == "header-only transcript"

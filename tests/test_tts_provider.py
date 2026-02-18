import pytest

from nanobot.providers.tts import OpenAITTSProvider, ToneTTSSynthesizer


@pytest.mark.asyncio
async def test_tone_tts_synthesizer_returns_wav_audio() -> None:
    synth = ToneTTSSynthesizer(sample_rate_hz=16000, tone_hz=440)
    result = await synth.synthesize("test audio")
    assert result is not None
    assert result.encoding == "wav"
    assert result.audio.startswith(b"RIFF")
    assert len(result.audio) > 256


@pytest.mark.asyncio
async def test_openai_tts_provider_calls_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        content = b"RIFFdummywav"

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json, timeout):  # type: ignore[no-untyped-def]
            self.calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": timeout,
                }
            )
            return DummyResponse()

    holder: dict[str, DummyClient] = {}

    def fake_async_client():
        client = DummyClient()
        holder["client"] = client
        return client

    monkeypatch.setattr("nanobot.providers.tts.httpx.AsyncClient", fake_async_client)
    provider = OpenAITTSProvider(
        api_key="k",
        api_base="https://openai.example.com",
        model="gpt-4o-mini-tts",
        voice="alloy",
        response_format="wav",
    )
    result = await provider.synthesize("hello")
    assert result is not None
    assert result.audio == b"RIFFdummywav"
    call = holder["client"].calls[0]
    assert call["url"] == "https://openai.example.com/v1/audio/speech"
    assert call["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_openai_tts_provider_supports_extra_headers_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        content = b"RIFFdummywav"

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json, timeout):  # type: ignore[no-untyped-def]
            assert url == "https://openai.example.com/v1/audio/speech"
            assert headers.get("X-App-Code") == "app-code"
            assert "Authorization" not in headers
            del json, timeout
            return DummyResponse()

    monkeypatch.setattr("nanobot.providers.tts.httpx.AsyncClient", lambda: DummyClient())
    provider = OpenAITTSProvider(
        api_key="",
        api_base="https://openai.example.com",
        extra_headers={"X-App-Code": "app-code"},
    )
    result = await provider.synthesize("hello")
    assert result is not None
    assert result.audio == b"RIFFdummywav"

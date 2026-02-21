"""Voice transcription providers."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from loguru import logger


class _OpenAICompatibleTranscriptionProvider:
    """Common implementation for OpenAI-compatible transcription endpoints."""

    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None,
        api_url: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.api_url = str(api_url).strip()
        self.model = str(model).strip()
        self.extra_headers = {str(k): str(v) for k, v in (extra_headers or {}).items() if str(k).strip()}

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe one audio file."""
        if not self.api_key and not self.extra_headers:
            logger.warning(f"{self.provider_name} credentials not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return ""

        try:
            with path.open("rb") as f:
                audio_bytes = f.read()
            return await self.transcribe_bytes(audio_bytes, filename=path.name)
        except Exception as e:
            logger.error(f"{self.provider_name} transcription error: {e}")
            return ""

    async def transcribe_bytes(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "audio.wav",
        content_type: str | None = None,
    ) -> str:
        """Transcribe in-memory audio bytes."""
        if not self.api_key and not self.extra_headers:
            logger.warning(f"{self.provider_name} credentials not configured for transcription")
            return ""
        if not audio_bytes:
            return ""

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        files = {
            "file": (filename, audio_bytes, content_type) if content_type else (filename, audio_bytes),
            "model": (None, self.model),
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    files=files,
                    timeout=60.0,
                )
            response.raise_for_status()
            data = response.json()
            return str(data.get("text") or "")
        except Exception as e:
            logger.error(f"{self.provider_name} transcription error: {e}")
            return ""


class GroqTranscriptionProvider(_OpenAICompatibleTranscriptionProvider):
    """Groq Whisper transcription provider."""

    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "whisper-large-v3",
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            api_url="https://api.groq.com/openai/v1/audio/transcriptions",
            model=model,
            extra_headers=extra_headers,
        )


class OpenAITranscriptionProvider(_OpenAICompatibleTranscriptionProvider):
    """OpenAI-compatible Whisper transcription provider."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_base: str | None = None,
        model: str = "whisper-1",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        base = (api_base or os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").strip()
        base = base.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        super().__init__(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            api_url=f"{base}/audio/transcriptions",
            model=model,
            extra_headers=extra_headers,
        )

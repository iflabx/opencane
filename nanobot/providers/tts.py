"""Text-to-speech providers for hardware server-audio mode."""

from __future__ import annotations

import io
import math
import os
import struct
import wave
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass(slots=True)
class SynthesizedAudio:
    """One synthesized audio payload."""

    audio: bytes
    encoding: str = "wav"
    mime: str = "audio/wav"
    sample_rate_hz: int = 16000


class OpenAITTSProvider:
    """OpenAI-compatible TTS provider (`/v1/audio/speech`)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_base: str | None = None,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        response_format: str = "wav",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        base = (api_base or os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").strip()
        base = base.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        self.api_url = f"{base}/audio/speech"
        self.model = str(model).strip() or "gpt-4o-mini-tts"
        self.voice = str(voice).strip() or "alloy"
        self.response_format = str(response_format).strip() or "wav"
        self.extra_headers = {str(k): str(v) for k, v in (extra_headers or {}).items() if str(k).strip()}

    async def synthesize(self, text: str) -> SynthesizedAudio | None:
        content = str(text or "").strip()
        if not content:
            return None
        if not self.api_key and not self.extra_headers:
            logger.warning("OpenAI credentials not configured for server_audio TTS")
            return None

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": content,
            "response_format": self.response_format,
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )
            resp.raise_for_status()
            audio_bytes = bytes(resp.content or b"")
            if not audio_bytes:
                return None
            return SynthesizedAudio(
                audio=audio_bytes,
                encoding=self.response_format,
                mime=_mime_for_format(self.response_format),
                sample_rate_hz=16000,
            )
        except Exception as e:
            logger.warning(f"OpenAI server_audio synthesis failed: {e}")
            return None


class ToneTTSSynthesizer:
    """Fallback local synthesizer that emits short WAV tones."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16000,
        tone_hz: int = 440,
    ) -> None:
        self.sample_rate_hz = max(8000, int(sample_rate_hz))
        self.tone_hz = max(220, int(tone_hz))

    async def synthesize(self, text: str) -> SynthesizedAudio | None:
        content = str(text or "").strip()
        if not content:
            return None
        duration_s = max(0.25, min(4.0, len(content) * 0.035))
        audio = _tone_wav_bytes(
            sample_rate=self.sample_rate_hz,
            duration_s=duration_s,
            freq_hz=self.tone_hz,
        )
        return SynthesizedAudio(
            audio=audio,
            encoding="wav",
            mime="audio/wav",
            sample_rate_hz=self.sample_rate_hz,
        )


def _tone_wav_bytes(
    *,
    sample_rate: int,
    duration_s: float,
    freq_hz: int,
) -> bytes:
    total_frames = max(1, int(sample_rate * duration_s))
    amplitude = 0.25 * 32767.0
    fade_frames = max(1, min(total_frames // 10, int(sample_rate * 0.02)))
    frames = bytearray()
    for i in range(total_frames):
        t = float(i) / float(sample_rate)
        wave_val = math.sin(2.0 * math.pi * float(freq_hz) * t)
        env = 1.0
        if i < fade_frames:
            env = float(i) / float(fade_frames)
        elif i > total_frames - fade_frames:
            env = float(total_frames - i) / float(fade_frames)
        sample = int(amplitude * wave_val * env)
        frames.extend(struct.pack("<h", sample))

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit PCM
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))
    return out.getvalue()


def _mime_for_format(fmt: str) -> str:
    value = str(fmt or "").strip().lower()
    if value == "mp3":
        return "audio/mpeg"
    if value == "opus":
        return "audio/opus"
    if value == "pcm":
        return "audio/pcm"
    if value == "flac":
        return "audio/flac"
    return "audio/wav"

"""Audio buffering and transcript extraction for hardware sessions."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from loguru import logger

from opencane.hardware.runtime.session_manager import DeviceSession

TranscribeFn = Callable[[bytes], Awaitable[str]]


@dataclass(slots=True)
class AudioCapture:
    """Capture buffers for one device session."""

    started: bool = False
    ordered_audio_chunks: dict[int, bytes] = field(default_factory=dict)
    ordered_text_chunks: dict[int, str] = field(default_factory=dict)
    pending_audio_chunks: dict[int, bytes] = field(default_factory=dict)
    prebuffer_audio_chunks: list[tuple[int, bytes]] = field(default_factory=list)
    total_audio_bytes: int = 0
    next_local_order: int = 1
    next_expected_audio_order: int | None = None
    vad_active: bool = False
    silence_chunks: int = 0
    speech_chunks: int = 0


class AudioPipeline:
    """Session-scoped audio buffering with optional transcription callback."""

    def __init__(
        self,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        transcribe_fn: TranscribeFn | None = None,
        enable_vad: bool = True,
        prebuffer_chunks: int = 3,
        jitter_window: int = 8,
        vad_silence_chunks: int = 6,
    ) -> None:
        self.max_bytes = max_bytes
        self.transcribe_fn = transcribe_fn
        self.enable_vad = bool(enable_vad)
        self.prebuffer_chunks = max(0, int(prebuffer_chunks))
        self.jitter_window = max(1, int(jitter_window))
        self.vad_silence_chunks = max(1, int(vad_silence_chunks))
        self._captures: dict[tuple[str, str], AudioCapture] = {}
        self._lock = asyncio.Lock()

    def start_capture(self, session: DeviceSession) -> None:
        key = (session.device_id, session.session_id)
        cap = self._captures.setdefault(key, AudioCapture())
        cap.ordered_audio_chunks.clear()
        cap.ordered_text_chunks.clear()
        cap.pending_audio_chunks.clear()
        cap.prebuffer_audio_chunks.clear()
        cap.total_audio_bytes = 0
        cap.next_local_order = 1
        cap.next_expected_audio_order = None
        cap.vad_active = False
        cap.silence_chunks = 0
        cap.speech_chunks = 0
        cap.started = True

    async def append_chunk(
        self,
        session: DeviceSession,
        payload: dict,
        *,
        event_seq: int | None = None,
    ) -> str:
        key = (session.device_id, session.session_id)
        async with self._lock:
            cap = self._captures.setdefault(key, AudioCapture())
            if not cap.started:
                cap.started = True
            order = _resolve_order(payload=payload, event_seq=event_seq, cap=cap)
            transcript_piece = payload.get("text") or payload.get("transcript")
            if transcript_piece:
                text_piece = str(transcript_piece).strip()
                if text_piece:
                    existing = cap.ordered_text_chunks.get(order)
                    if existing and existing != text_piece:
                        order = _next_free_order(order, cap)
                    cap.ordered_text_chunks[order] = text_piece
            audio_b64 = payload.get("audio_b64") or payload.get("audio")
            if audio_b64:
                try:
                    chunk = base64.b64decode(audio_b64)
                except Exception:
                    logger.debug("Invalid base64 audio payload ignored")
                    chunk = b""
                if chunk and not _audio_order_exists(cap, order):
                    speech = _resolve_speech_flag(payload)
                    self._append_audio_chunk(cap, order, chunk, speech=speech)
            return _compose_text(cap)

    async def finalize_capture(self, session: DeviceSession, payload: dict) -> str:
        """Return transcript from explicit payload/text chunks/transcriber fallback."""
        explicit = payload.get("transcript") or payload.get("text")
        if explicit:
            self.reset_capture(session)
            return str(explicit).strip()

        key = (session.device_id, session.session_id)
        async with self._lock:
            cap = self._captures.pop(key, None)
        if not cap:
            return ""

        # Finalize buffered chunks for transcription fallback.
        self._flush_prebuffer(cap)
        self._flush_pending_audio(cap, force=True)

        transcript = _compose_text(cap)
        if transcript:
            return transcript

        audio_data = b"".join(
            cap.ordered_audio_chunks[k]
            for k in sorted(cap.ordered_audio_chunks)
        )
        if not audio_data or not self.transcribe_fn:
            return ""
        try:
            return (await self.transcribe_fn(audio_data)).strip()
        except Exception as e:
            logger.warning(f"Audio transcription failed: {e}")
            return ""

    async def partial_transcript(self, session: DeviceSession, *, max_chars: int = 160) -> str:
        """Build current partial transcript using ordered text chunks."""
        key = (session.device_id, session.session_id)
        async with self._lock:
            cap = self._captures.get(key)
            if not cap:
                return ""
            text = _compose_text(cap)
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 3)].rstrip() + "..."

    def reset_capture(self, session: DeviceSession) -> None:
        self._captures.pop((session.device_id, session.session_id), None)

    def _append_audio_chunk(
        self,
        cap: AudioCapture,
        order: int,
        chunk: bytes,
        *,
        speech: bool | None,
    ) -> None:
        if cap.total_audio_bytes + len(chunk) > self.max_bytes:
            logger.warning("Audio buffer reached limit; dropping chunk")
            return

        if not self.enable_vad:
            self._store_pending_audio(cap, order, chunk)
            self._flush_pending_audio(cap)
            return

        if speech is None:
            # Keep previous behavior when source does not provide VAD hint.
            speech = True

        if speech:
            cap.vad_active = True
            cap.silence_chunks = 0
            cap.speech_chunks += 1
            self._flush_prebuffer(cap)
            self._store_pending_audio(cap, order, chunk)
            self._flush_pending_audio(cap)
            return

        # Non-speech frame.
        if cap.vad_active:
            cap.silence_chunks += 1
            self._store_pending_audio(cap, order, chunk)
            self._flush_pending_audio(cap)
            if cap.silence_chunks >= self.vad_silence_chunks:
                cap.vad_active = False
            return

        # Before speech starts, keep a small prebuffer window.
        self._store_prebuffer_audio(cap, order, chunk)

    def _store_pending_audio(self, cap: AudioCapture, order: int, chunk: bytes) -> None:
        if order in cap.pending_audio_chunks or order in cap.ordered_audio_chunks:
            return
        cap.pending_audio_chunks[order] = chunk
        cap.total_audio_bytes += len(chunk)
        if cap.next_expected_audio_order is None:
            cap.next_expected_audio_order = min(cap.pending_audio_chunks)

    def _store_prebuffer_audio(self, cap: AudioCapture, order: int, chunk: bytes) -> None:
        if self.prebuffer_chunks <= 0:
            return
        for existing_order, _ in cap.prebuffer_audio_chunks:
            if existing_order == order:
                return
        cap.prebuffer_audio_chunks.append((order, chunk))
        cap.total_audio_bytes += len(chunk)
        overflow = len(cap.prebuffer_audio_chunks) - self.prebuffer_chunks
        if overflow > 0:
            for _ in range(overflow):
                _, dropped = cap.prebuffer_audio_chunks.pop(0)
                cap.total_audio_bytes = max(0, cap.total_audio_bytes - len(dropped))

    def _flush_prebuffer(self, cap: AudioCapture) -> None:
        if not cap.prebuffer_audio_chunks:
            return
        for order, chunk in sorted(cap.prebuffer_audio_chunks, key=lambda item: item[0]):
            if order in cap.pending_audio_chunks or order in cap.ordered_audio_chunks:
                continue
            cap.pending_audio_chunks[order] = chunk
            if cap.next_expected_audio_order is None:
                cap.next_expected_audio_order = order
        cap.prebuffer_audio_chunks.clear()

    def _flush_pending_audio(self, cap: AudioCapture, *, force: bool = False) -> None:
        if not cap.pending_audio_chunks:
            return
        if force:
            for order in sorted(cap.pending_audio_chunks):
                cap.ordered_audio_chunks[order] = cap.pending_audio_chunks[order]
            cap.pending_audio_chunks.clear()
            cap.next_expected_audio_order = None
            return

        if cap.next_expected_audio_order is None:
            cap.next_expected_audio_order = min(cap.pending_audio_chunks)

        while (
            cap.next_expected_audio_order is not None
            and cap.next_expected_audio_order in cap.pending_audio_chunks
        ):
            order = int(cap.next_expected_audio_order)
            cap.ordered_audio_chunks[order] = cap.pending_audio_chunks.pop(order)
            cap.next_expected_audio_order = order + 1

        while len(cap.pending_audio_chunks) > self.jitter_window:
            order = min(cap.pending_audio_chunks)
            cap.ordered_audio_chunks[order] = cap.pending_audio_chunks.pop(order)
            if cap.next_expected_audio_order is None:
                cap.next_expected_audio_order = order + 1
            else:
                cap.next_expected_audio_order = max(int(cap.next_expected_audio_order), order + 1)


def _to_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _resolve_order(
    *,
    payload: dict,
    event_seq: int | None,
    cap: AudioCapture,
) -> int:
    for key in ("chunk_index", "chunk_idx", "frame_index", "index", "order", "timestamp"):
        value = _to_int(payload.get(key))
        if value is not None and value >= 0:
            cap.next_local_order = max(cap.next_local_order, value + 1)
            return value
    if event_seq is not None and int(event_seq) >= 0:
        value = int(event_seq)
        cap.next_local_order = max(cap.next_local_order, value + 1)
        return value
    value = cap.next_local_order
    cap.next_local_order += 1
    return value


def _next_free_order(order: int, cap: AudioCapture) -> int:
    next_order = max(int(order), cap.next_local_order)
    while next_order in cap.ordered_text_chunks:
        next_order += 1
    cap.next_local_order = max(cap.next_local_order, next_order + 1)
    return next_order


def _compose_text(cap: AudioCapture) -> str:
    parts = [
        cap.ordered_text_chunks[k].strip()
        for k in sorted(cap.ordered_text_chunks)
        if str(cap.ordered_text_chunks[k]).strip()
    ]
    return " ".join(parts).strip()


def _audio_order_exists(cap: AudioCapture, order: int) -> bool:
    if order in cap.ordered_audio_chunks:
        return True
    if order in cap.pending_audio_chunks:
        return True
    return any(existing == order for existing, _ in cap.prebuffer_audio_chunks)


def _resolve_speech_flag(payload: dict) -> bool | None:
    for key in ("is_speech", "speech", "vad_speech", "vad", "voice"):
        if key not in payload:
            continue
        return _to_bool(payload.get(key))
    transcript_piece = payload.get("text") or payload.get("transcript")
    if str(transcript_piece or "").strip():
        return True
    return None


def _to_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "speech", "voice"}:
        return True
    if text in {"0", "false", "no", "off", "silence", "noise"}:
        return False
    return None

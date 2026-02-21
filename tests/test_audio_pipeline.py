from __future__ import annotations

import base64

import pytest

from opencane.hardware.runtime.audio_pipeline import AudioPipeline
from opencane.hardware.runtime.session_manager import DeviceSession


@pytest.mark.asyncio
async def test_audio_pipeline_reorders_text_chunks_for_partial_and_final() -> None:
    session = DeviceSession(device_id="dev-1", session_id="sess-1")
    pipeline = AudioPipeline()
    pipeline.start_capture(session)

    await pipeline.append_chunk(
        session,
        {"text": "world", "chunk_index": 2},
        event_seq=5,
    )
    await pipeline.append_chunk(
        session,
        {"text": "hello", "chunk_index": 1},
        event_seq=4,
    )

    partial = await pipeline.partial_transcript(session)
    final = await pipeline.finalize_capture(session, {})
    assert partial == "hello world"
    assert final == "hello world"


@pytest.mark.asyncio
async def test_audio_pipeline_reorders_audio_chunks_before_transcribe() -> None:
    session = DeviceSession(device_id="dev-2", session_id="sess-2")
    seen: list[bytes] = []

    async def _transcribe(audio: bytes) -> str:
        seen.append(audio)
        return "ok"

    pipeline = AudioPipeline(transcribe_fn=_transcribe)
    pipeline.start_capture(session)

    await pipeline.append_chunk(
        session,
        {"audio_b64": base64.b64encode(b"BB").decode("ascii"), "chunk_index": 2},
        event_seq=10,
    )
    await pipeline.append_chunk(
        session,
        {"audio_b64": base64.b64encode(b"AA").decode("ascii"), "chunk_index": 1},
        event_seq=9,
    )
    final = await pipeline.finalize_capture(session, {})
    assert final == "ok"
    assert seen == [b"AABB"]


@pytest.mark.asyncio
async def test_audio_pipeline_vad_prebuffer_flushes_into_speech_segment() -> None:
    session = DeviceSession(device_id="dev-3", session_id="sess-3")
    seen: list[bytes] = []

    async def _transcribe(audio: bytes) -> str:
        seen.append(audio)
        return "ok"

    pipeline = AudioPipeline(
        transcribe_fn=_transcribe,
        enable_vad=True,
        prebuffer_chunks=2,
    )
    pipeline.start_capture(session)

    await pipeline.append_chunk(
        session,
        {
            "audio_b64": base64.b64encode(b"AA").decode("ascii"),
            "chunk_index": 1,
            "is_speech": False,
        },
        event_seq=1,
    )
    await pipeline.append_chunk(
        session,
        {
            "audio_b64": base64.b64encode(b"BB").decode("ascii"),
            "chunk_index": 2,
            "is_speech": True,
        },
        event_seq=2,
    )

    final = await pipeline.finalize_capture(session, {})
    assert final == "ok"
    assert seen == [b"AABB"]


@pytest.mark.asyncio
async def test_audio_pipeline_jitter_window_tolerates_gaps_and_late_chunks() -> None:
    session = DeviceSession(device_id="dev-4", session_id="sess-4")
    seen: list[bytes] = []

    async def _transcribe(audio: bytes) -> str:
        seen.append(audio)
        return "ok"

    pipeline = AudioPipeline(
        transcribe_fn=_transcribe,
        enable_vad=False,
        jitter_window=1,
    )
    pipeline.start_capture(session)

    await pipeline.append_chunk(
        session,
        {"audio_b64": base64.b64encode(b"E").decode("ascii"), "chunk_index": 5},
        event_seq=5,
    )
    await pipeline.append_chunk(
        session,
        {"audio_b64": base64.b64encode(b"G").decode("ascii"), "chunk_index": 7},
        event_seq=7,
    )
    await pipeline.append_chunk(
        session,
        {"audio_b64": base64.b64encode(b"F").decode("ascii"), "chunk_index": 6},
        event_seq=6,
    )

    final = await pipeline.finalize_capture(session, {})
    assert final == "ok"
    assert seen == [b"EFG"]

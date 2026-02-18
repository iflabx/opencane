"""Canonical event/command envelope for device integrations."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


def now_ms() -> int:
    """Current timestamp in milliseconds."""
    return int(time.time() * 1000)


class DeviceEventType(StrEnum):
    """Canonical inbound event types emitted by device adapters."""

    HELLO = "hello"
    HEARTBEAT = "heartbeat"
    LISTEN_START = "listen_start"
    AUDIO_CHUNK = "audio_chunk"
    LISTEN_STOP = "listen_stop"
    ABORT = "abort"
    IMAGE_READY = "image_ready"
    TELEMETRY = "telemetry"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


class DeviceCommandType(StrEnum):
    """Canonical outbound command types sent to devices."""

    HELLO_ACK = "hello_ack"
    STT_PARTIAL = "stt_partial"
    STT_FINAL = "stt_final"
    TTS_START = "tts_start"
    TTS_CHUNK = "tts_chunk"
    TTS_STOP = "tts_stop"
    TASK_UPDATE = "task_update"
    TOOL_CALL = "tool_call"
    SET_CONFIG = "set_config"
    OTA_PLAN = "ota_plan"
    CLOSE = "close"
    ACK = "ack"


@dataclass(slots=True)
class CanonicalEnvelope:
    """Unified envelope used internally by runtime and adapters."""

    version: str
    msg_id: str
    device_id: str
    session_id: str
    seq: int
    ts: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        default_device_id: str | None = None,
        default_session_id: str | None = None,
    ) -> "CanonicalEnvelope":
        """Create a canonical envelope from raw dict data."""
        version = str(data.get("version", data.get("v", "0.1")))
        msg_id = str(data.get("msg_id", data.get("id", uuid.uuid4().hex)))
        device_id = str(
            data.get("device_id")
            or data.get("deviceId")
            or default_device_id
            or ""
        ).strip()
        session_id = str(
            data.get("session_id")
            or data.get("sessionId")
            or default_session_id
            or ""
        ).strip()
        raw_seq = data.get("seq", 0)
        raw_ts = data.get("ts", now_ms())
        msg_type = str(data.get("type", "")).strip()
        payload = data.get("payload", {})

        if not isinstance(payload, dict):
            payload = {"value": payload}
        try:
            seq = int(raw_seq)
        except (TypeError, ValueError):
            seq = 0
        try:
            ts = int(raw_ts)
        except (TypeError, ValueError):
            ts = now_ms()

        if not device_id:
            raise ValueError("device_id is required")
        if not msg_type:
            raise ValueError("type is required")

        if not session_id:
            session_id = f"{device_id}-{uuid.uuid4().hex[:8]}"

        return cls(
            version=version,
            msg_id=msg_id,
            device_id=device_id,
            session_id=session_id,
            seq=max(0, seq),
            ts=max(0, ts),
            type=msg_type,
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return asdict(self)


def make_event(
    event_type: DeviceEventType | str,
    *,
    device_id: str,
    session_id: str,
    seq: int = 0,
    payload: dict[str, Any] | None = None,
    version: str = "0.1",
) -> CanonicalEnvelope:
    """Factory helper for inbound events."""
    return CanonicalEnvelope(
        version=version,
        msg_id=uuid.uuid4().hex,
        device_id=device_id,
        session_id=session_id,
        seq=max(0, seq),
        ts=now_ms(),
        type=str(event_type),
        payload=payload or {},
    )


def make_command(
    command_type: DeviceCommandType | str,
    *,
    device_id: str,
    session_id: str,
    seq: int = 0,
    payload: dict[str, Any] | None = None,
    version: str = "0.1",
) -> CanonicalEnvelope:
    """Factory helper for outbound commands."""
    return CanonicalEnvelope(
        version=version,
        msg_id=uuid.uuid4().hex,
        device_id=device_id,
        session_id=session_id,
        seq=max(0, seq),
        ts=now_ms(),
        type=str(command_type),
        payload=payload or {},
    )

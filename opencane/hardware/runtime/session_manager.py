"""Session and state management for hardware device connections."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


class ConnectionState(StrEnum):
    """High-level runtime state for one device session."""

    CONNECTING = "connecting"
    READY = "ready"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    CLOSED = "closed"


@dataclass(slots=True)
class DeviceSession:
    """In-memory runtime session for one connected device."""

    device_id: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: ConnectionState = ConnectionState.CONNECTING
    created_at_ms: int = field(default_factory=_now_ms)
    last_seen_ms: int = field(default_factory=_now_ms)
    last_seq: int = -1
    last_outbound_seq: int = 0
    closed_at_ms: int = 0
    close_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_seen_ms = _now_ms()

    def to_status(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class DeviceSessionManager:
    """Tracks active sessions and performs sequence de-duplication."""

    def __init__(self, *, persistence_store: Any | None = None) -> None:
        self._sessions: dict[tuple[str, str], DeviceSession] = {}
        self._latest_by_device: dict[str, DeviceSession] = {}
        self._persistence_store = persistence_store

    def get_or_create(
        self,
        device_id: str,
        session_id: str | None = None,
    ) -> DeviceSession:
        if session_id:
            key = (device_id, session_id)
            if key in self._sessions:
                return self._sessions[key]
        else:
            existing = self._latest_by_device.get(device_id)
            if existing and existing.state != ConnectionState.CLOSED:
                return existing

        session = DeviceSession(device_id=device_id, session_id=session_id or uuid.uuid4().hex)
        self._sessions[(session.device_id, session.session_id)] = session
        self._latest_by_device[device_id] = session
        self._persist_upsert(session)
        return session

    def get(self, device_id: str, session_id: str) -> DeviceSession | None:
        return self._sessions.get((device_id, session_id))

    def get_latest(self, device_id: str) -> DeviceSession | None:
        return self._latest_by_device.get(device_id)

    def update_state(
        self,
        device_id: str,
        session_id: str,
        state: ConnectionState,
        *,
        persist: bool = True,
    ) -> DeviceSession:
        session = self.get_or_create(device_id, session_id)
        session.state = state
        if state != ConnectionState.CLOSED:
            session.closed_at_ms = 0
            session.close_reason = ""
        session.touch()
        if persist:
            self._persist_upsert(session)
        return session

    def update_metadata(
        self,
        device_id: str,
        session_id: str,
        metadata: dict[str, Any],
        *,
        persist: bool = True,
    ) -> DeviceSession:
        session = self.get_or_create(device_id, session_id)
        session.metadata.update(metadata)
        session.touch()
        if persist:
            self._persist_upsert(session)
        return session

    def update_telemetry(
        self,
        device_id: str,
        session_id: str,
        telemetry: dict[str, Any],
        *,
        persist: bool = True,
    ) -> DeviceSession:
        session = self.get_or_create(device_id, session_id)
        session.telemetry.update(telemetry)
        session.touch()
        if persist:
            self._persist_upsert(session)
        return session

    def check_and_commit_seq(
        self,
        device_id: str,
        session_id: str,
        seq: int,
        *,
        persist: bool = True,
    ) -> bool:
        """Return True when seq is new enough and commit it."""
        session = self.get_or_create(device_id, session_id)
        session.touch()
        if seq < 0:
            if persist:
                self._persist_upsert(session)
            return True
        if seq <= session.last_seq:
            if persist:
                self._persist_upsert(session)
            return False
        session.last_seq = seq
        if persist:
            self._persist_upsert(session)
        return True

    def next_outbound_seq(
        self,
        device_id: str,
        session_id: str,
        *,
        persist: bool = True,
    ) -> int:
        """Allocate next outbound sequence for one session."""
        session = self.get_or_create(device_id, session_id)
        session.last_outbound_seq = max(1, session.last_outbound_seq + 1)
        session.touch()
        if persist:
            self._persist_upsert(session)
        return session.last_outbound_seq

    def close(self, device_id: str, session_id: str, reason: str = "closed") -> None:
        session = self.get_or_create(device_id, session_id)
        session.state = ConnectionState.CLOSED
        session.touch()
        session.closed_at_ms = session.last_seen_ms
        session.close_reason = str(reason or "closed")
        self._persist_close(session, reason=session.close_reason)
        current = self._latest_by_device.get(device_id)
        if current and current.session_id == session_id:
            self._latest_by_device.pop(device_id, None)

    def status(self, device_id: str) -> dict[str, Any] | None:
        session = self.get_latest(device_id)
        return session.to_status() if session else None

    def all_status(self) -> list[dict[str, Any]]:
        return [s.to_status() for s in self._sessions.values()]

    def _persist_upsert(self, session: DeviceSession) -> None:
        store = self._persistence_store
        if store is None or not hasattr(store, "upsert_device_session"):
            return
        try:
            store.upsert_device_session(
                device_id=session.device_id,
                session_id=session.session_id,
                state=session.state.value,
                created_at_ms=session.created_at_ms,
                last_seen_ms=session.last_seen_ms,
                last_seq=session.last_seq,
                last_outbound_seq=session.last_outbound_seq,
                metadata=dict(session.metadata),
                telemetry=dict(session.telemetry),
                closed_at_ms=int(session.closed_at_ms),
                close_reason=str(session.close_reason or ""),
                updated_at_ms=session.last_seen_ms,
            )
        except Exception:
            return

    def _persist_close(self, session: DeviceSession, *, reason: str) -> None:
        store = self._persistence_store
        if store is None:
            return
        if hasattr(store, "close_device_session"):
            try:
                store.close_device_session(
                    device_id=session.device_id,
                    session_id=session.session_id,
                    reason=reason,
                    closed_at_ms=session.closed_at_ms,
                )
                return
            except Exception:
                pass
        self._persist_upsert(session)

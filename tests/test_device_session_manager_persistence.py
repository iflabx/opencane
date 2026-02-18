from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nanobot.hardware.adapter.mock_adapter import MockAdapter
from nanobot.hardware.protocol import DeviceEventType, make_event
from nanobot.hardware.runtime.connection import DeviceRuntimeCore
from nanobot.hardware.runtime.session_manager import ConnectionState, DeviceSessionManager


class _FakeSessionStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.closes: list[dict[str, Any]] = []

    def upsert_device_session(self, **kwargs: Any) -> None:
        self.upserts.append(dict(kwargs))

    def close_device_session(self, **kwargs: Any) -> None:
        self.closes.append(dict(kwargs))


class _FakeAgentLoop:
    async def process_direct(self, content: str, **kwargs: Any) -> str:
        del kwargs
        return content


class _FakeLifelogWithStore:
    def __init__(self, store: _FakeSessionStore) -> None:
        self.store = store


def test_device_session_manager_persists_lifecycle_events() -> None:
    store = _FakeSessionStore()
    manager = DeviceSessionManager(persistence_store=store)
    manager.get_or_create("dev-1", "sess-1")
    manager.update_state("dev-1", "sess-1", ConnectionState.READY)
    manager.update_metadata("dev-1", "sess-1", {"firmware": "v1"})
    manager.update_telemetry("dev-1", "sess-1", {"battery": 82})
    assert manager.check_and_commit_seq("dev-1", "sess-1", 7) is True
    assert manager.next_outbound_seq("dev-1", "sess-1") == 1
    manager.close("dev-1", "sess-1", reason="manual_abort")

    assert len(store.upserts) >= 4
    assert store.upserts[0]["state"] == ConnectionState.CONNECTING.value
    assert any(int(item.get("last_seq", -1)) == 7 for item in store.upserts)
    assert any(int(item.get("last_outbound_seq", 0)) == 1 for item in store.upserts)
    assert store.upserts[-1]["state"] in {ConnectionState.READY.value, ConnectionState.CLOSED.value}
    assert store.closes
    assert store.closes[-1]["reason"] == "manual_abort"


@pytest.mark.asyncio
async def test_runtime_auto_wires_session_persistence_from_lifelog_store() -> None:
    adapter = MockAdapter()
    store = _FakeSessionStore()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=_FakeAgentLoop(),
        lifelog_service=_FakeLifelogWithStore(store),
    )
    await runtime.start()
    try:
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id="dev-runtime", session_id="sess-runtime", seq=1)
        )
        await asyncio.sleep(0.2)
        assert store.upserts
        assert any(str(item.get("device_id")) == "dev-runtime" for item in store.upserts)
    finally:
        await runtime.stop()
    assert store.closes
    assert any(str(item.get("reason")) == "runtime_stop" for item in store.closes)

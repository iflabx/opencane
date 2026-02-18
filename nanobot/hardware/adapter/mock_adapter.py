"""In-memory adapter used for local simulation and tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from nanobot.hardware.adapter.base import GatewayAdapter
from nanobot.hardware.protocol import CanonicalEnvelope

_SENTINEL = object()


class MockAdapter(GatewayAdapter):
    """Queue-backed adapter that can be fed by tests or debug endpoints."""

    name = "mock"
    transport = "in-memory"

    def __init__(self) -> None:
        self._running = False
        self._inbound: asyncio.Queue[CanonicalEnvelope | object] = asyncio.Queue()
        self._outbound: asyncio.Queue[CanonicalEnvelope] = asyncio.Queue()

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        await self._inbound.put(_SENTINEL)

    async def recv_events(self) -> AsyncIterator[CanonicalEnvelope]:
        while self._running:
            event = await self._inbound.get()
            if event is _SENTINEL:
                break
            yield event

    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        await self._outbound.put(cmd)

    async def inject_event(self, event: CanonicalEnvelope | dict[str, Any]) -> CanonicalEnvelope:
        """Inject raw dict or canonical event into adapter inbound queue."""
        canonical = event if isinstance(event, CanonicalEnvelope) else CanonicalEnvelope.from_dict(event)
        await self._inbound.put(canonical)
        return canonical

    async def next_command(self, timeout_s: float = 1.0) -> CanonicalEnvelope:
        """Await next outbound command sent by runtime."""
        return await asyncio.wait_for(self._outbound.get(), timeout=timeout_s)

    def pending_commands(self) -> list[CanonicalEnvelope]:
        """Drain all currently queued outbound commands."""
        items: list[CanonicalEnvelope] = []
        while True:
            try:
                items.append(self._outbound.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items


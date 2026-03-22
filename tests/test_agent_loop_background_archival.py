from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.events import InboundMessage
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_close_mcp_drains_background_archival_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        memory_window=2,
    )

    session = loop.sessions.get_or_create("cli:chat-archive")
    for i in range(3):
        session.add_message("user", f"user-{i}")
    loop.sessions.save(session)

    archived = asyncio.Event()

    async def _fake_consolidate(target_session, archive_all: bool = False):  # type: ignore[no-untyped-def]
        del target_session, archive_all
        await asyncio.sleep(0.05)
        archived.set()

    monkeypatch.setattr(loop, "_consolidate_memory", _fake_consolidate)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-archive", content="/new")
    )
    assert response is not None
    assert "new session started" in response.content.lower()
    assert not archived.is_set()

    await loop.close_mcp()
    assert archived.is_set()
    assert loop._background_tasks == []


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
        return True

    monkeypatch.setattr(loop, "_consolidate_memory", _fake_consolidate)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-archive", content="hello")
    )
    assert response is not None
    assert response.content == "ok"
    assert not archived.is_set()

    await loop.close_mcp()
    assert archived.is_set()
    assert loop._background_tasks == []


@pytest.mark.asyncio
async def test_new_keeps_session_when_archival_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        memory_window=2,
    )

    session = loop.sessions.get_or_create("cli:chat-archive")
    session.add_message("user", "u1")
    session.add_message("assistant", "a1")
    loop.sessions.save(session)

    async def _fake_consolidate(target_session, archive_all: bool = False):  # type: ignore[no-untyped-def]
        del target_session, archive_all
        return False

    monkeypatch.setattr(loop, "_consolidate_memory", _fake_consolidate)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-archive", content="/new")
    )
    assert response is not None
    assert "could not start a new session" in response.content.lower()

    session_after = loop.sessions.get_or_create("cli:chat-archive")
    assert len(session_after.messages) == 2


@pytest.mark.asyncio
async def test_new_waits_for_inflight_consolidation_and_archives_tail_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        memory_window=4,
    )

    session = loop.sessions.get_or_create("cli:chat-archive")
    for i in range(6):
        session.add_message("user", f"user-{i}")
        session.add_message("assistant", f"assistant-{i}")
    loop.sessions.save(session)

    started = asyncio.Event()
    release = asyncio.Event()
    archived_count = -1

    async def _fake_consolidate(target_session, archive_all: bool = False):  # type: ignore[no-untyped-def]
        nonlocal archived_count
        if archive_all:
            archived_count = len(target_session.messages)
            return True
        started.set()
        await release.wait()
        target_session.last_consolidated = len(target_session.messages) - 2
        return True

    monkeypatch.setattr(loop, "_consolidate_memory", _fake_consolidate)

    first = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-archive", content="hello")
    )
    assert first is not None
    assert first.content == "ok"
    await started.wait()

    pending_new = asyncio.create_task(
        loop._process_message(
            InboundMessage(channel="cli", sender_id="u1", chat_id="chat-archive", content="/new")
        )
    )
    await asyncio.sleep(0.02)
    assert not pending_new.done()

    release.set()
    response = await pending_new
    assert response is not None
    assert "new session started" in response.content.lower()
    assert archived_count == 2

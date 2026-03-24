from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.events import InboundMessage
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse


class _CountingProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.calls = 0

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        self.calls += 1
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "fake-model"


class _UsageSequenceProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__(api_key=None, api_base=None)
        self._responses = responses
        self._idx = 0

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        idx = min(self._idx, len(self._responses) - 1)
        self._idx += 1
        return self._responses[idx]

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_status_command_returns_runtime_snapshot_without_provider_call(
    tmp_path: Path,
) -> None:
    provider = _CountingProvider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
    )
    session = loop.sessions.get_or_create("cli:chat-status")
    session.add_message("user", "u1")
    session.add_message("assistant", "a1")
    loop.sessions.save(session)
    loop._start_time = time.time() - 125
    loop._last_usage = {"prompt_tokens": 1200, "completion_tokens": 34}

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-status", content="/status")
    )

    assert response is not None
    assert "OpenCane v" in response.content
    assert "Model: fake-model" in response.content
    assert "Last tokens: 1200 in / 34 out" in response.content
    assert "Session: 2 messages" in response.content
    assert "Subagents: 0 active" in response.content
    assert "Queue: 0 pending" in response.content
    assert "Uptime: 2m 5s" in response.content
    assert response.metadata == {"render_as": "text"}
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_help_command_mentions_status(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_CountingProvider(),
        workspace=tmp_path,
    )

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-help", content="/help")
    )
    assert response is not None
    assert "/status" in response.content
    assert response.metadata == {"render_as": "text"}


@pytest.mark.asyncio
async def test_run_intercepts_status_before_main_processing(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_CountingProvider(),
        workspace=tmp_path,
    )

    mocked_process = AsyncMock()
    loop._process_message = mocked_process  # type: ignore[method-assign]

    await bus.publish_inbound(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-status", content="/status")
    )

    run_task = asyncio.create_task(loop.run())
    try:
        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.5)
        assert "OpenCane v" in outbound.content
        assert outbound.metadata == {"render_as": "text"}
        mocked_process.assert_not_awaited()
    finally:
        loop.stop()
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task


@pytest.mark.asyncio
async def test_run_agent_loop_resets_usage_when_provider_omits_usage(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_UsageSequenceProvider(
            [
                LLMResponse(content="first", usage={"prompt_tokens": 9, "completion_tokens": 4}),
                LLMResponse(content="second", usage={}),
            ]
        ),
        workspace=tmp_path,
    )

    await loop._run_agent_loop(
        [{"role": "user", "content": "hi"}],
        allowed_tool_names=set(),
    )
    assert loop._last_usage == {"prompt_tokens": 9, "completion_tokens": 4}

    await loop._run_agent_loop(
        [{"role": "user", "content": "hi"}],
        allowed_tool_names=set(),
    )
    assert loop._last_usage == {"prompt_tokens": 0, "completion_tokens": 0}

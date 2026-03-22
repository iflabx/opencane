from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _InterimThenToolProvider(LLMProvider):
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
        if self.calls == 1:
            return LLMResponse(content="Let me check this first.")
        if self.calls == 2:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="msg-1",
                        name="message",
                        arguments={"content": "Tool progress update", "chat_id": "chat-progress"},
                    )
                ],
            )
        return LLMResponse(content="Done after tool call.")

    def get_default_model(self) -> str:
        return "fake-model"


class _TextOnlyProvider(LLMProvider):
    def __init__(self, outputs: list[str]) -> None:
        super().__init__(api_key=None, api_base=None)
        self.outputs = outputs
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
        index = min(self.calls - 1, len(self.outputs) - 1)
        return LLMResponse(content=self.outputs[index])

    def get_default_model(self) -> str:
        return "fake-model"


class _InterimToolThenEmptyProvider(LLMProvider):
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
        if self.calls == 1:
            return LLMResponse(content="Interim text before tools.")
        if self.calls == 2:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="msg-2",
                        name="message",
                        arguments={"content": "progress from tool"},
                    )
                ],
            )
        return LLMResponse(content="")

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_agent_loop_retries_interim_text_then_executes_tool(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _InterimThenToolProvider()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    result = await loop.process_direct(
        "run tool flow",
        session_key="cli:interim-retry-tools",
        channel="cli",
        chat_id="chat-1",
    )

    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert outbound.content == "Tool progress update"
    assert result is not None
    assert result.content == "Done after tool call."
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_agent_loop_retries_interim_text_only_once(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _TextOnlyProvider(["first interim", "second final", "third should-not-run"])
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    result = await loop.process_direct(
        "text only",
        session_key="cli:interim-retry-once",
        channel="cli",
        chat_id="chat-2",
    )

    assert result is not None
    assert result.content == "second final"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_agent_loop_skips_interim_retry_without_available_tools(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _TextOnlyProvider(["first response", "second should-not-run"])
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    result = await loop.process_direct(
        "no tools allowed",
        session_key="cli:no-tools-retry",
        channel="cli",
        chat_id="chat-3",
        allowed_tool_names=set(),
    )

    assert result is not None
    assert result.content == "first response"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_agent_loop_falls_back_to_interim_when_retry_returns_empty(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _TextOnlyProvider(["first interim answer", ""])
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    result = await loop.process_direct(
        "fallback please",
        session_key="cli:interim-fallback",
        channel="cli",
        chat_id="chat-4",
    )

    assert result is not None
    assert result.content == "first interim answer"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_agent_loop_does_not_use_interim_fallback_after_tool_usage(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _InterimToolThenEmptyProvider()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    result = await loop.process_direct(
        "tool then empty",
        session_key="cli:interim-no-fallback-after-tools",
        channel="cli",
        chat_id="chat-5",
    )

    assert result is None
    assert provider.calls == 3

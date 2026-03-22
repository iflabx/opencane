from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.events import InboundMessage
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _MessageThenFinalProvider(LLMProvider):
    def __init__(
        self,
        *,
        tool_channel: str | None = None,
        tool_chat_id: str | None = None,
    ) -> None:
        super().__init__(api_key=None, api_base=None)
        self._turn = 0
        self._tool_channel = tool_channel
        self._tool_chat_id = tool_chat_id

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        self._turn += 1
        if self._turn == 1:
            args: dict[str, Any] = {"content": "tool-message"}
            if self._tool_channel:
                args["channel"] = self._tool_channel
            if self._tool_chat_id:
                args["chat_id"] = self._tool_chat_id
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="tool-msg-1",
                        name="message",
                        arguments=args,
                    )
                ],
            )
        return LLMResponse(content="final-message")

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_process_message_suppresses_final_when_message_tool_sent_same_target(
    tmp_path: Path,
) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_MessageThenFinalProvider(),
        workspace=tmp_path,
    )

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="hello")
    )
    assert response is None

    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert outbound.channel == "cli"
    assert outbound.chat_id == "chat-a"
    assert outbound.content == "tool-message"


@pytest.mark.asyncio
async def test_process_message_keeps_final_when_message_tool_sent_other_target(
    tmp_path: Path,
) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_MessageThenFinalProvider(tool_channel="cli", tool_chat_id="chat-b"),
        workspace=tmp_path,
    )

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="hello")
    )
    assert response is not None
    assert response.channel == "cli"
    assert response.chat_id == "chat-a"
    assert response.content == "final-message"

    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert outbound.channel == "cli"
    assert outbound.chat_id == "chat-b"
    assert outbound.content == "tool-message"

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _FakeProvider(LLMProvider):
    def __init__(self, text: str) -> None:
        super().__init__(api_key=None, api_base=None)
        self.text = text

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        return LLMResponse(content=self.text)

    def get_default_model(self) -> str:
        return "fake-model"


class _FakeToolCallProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self._turn = 0

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
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="tool-msg-1",
                        name="message",
                        arguments={"content": "请继续直行"},
                    )
                ],
            )
        return LLMResponse(content="任务已通知")

    def get_default_model(self) -> str:
        return "fake-model"


class _CaptureProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.last_messages: list[dict[str, Any]] = []

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del tools, model, max_tokens, temperature
        self.last_messages = [dict(item) for item in messages]
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "fake-model"


class _FakeSafetyPolicy:
    enabled = True

    def evaluate(self, **kwargs):  # type: ignore[no-untyped-def]
        text = str(kwargs.get("text") or "")
        return {
            "text": f"safe:{text}",
            "risk_level": "P2",
            "confidence": 0.6,
            "downgraded": True,
            "reason": "test",
            "flags": ["test"],
            "policy_version": "test-v1",
            "rule_ids": ["test"],
            "evidence": {"mock": True},
        }


class _FakeLifelogService:
    def __init__(self) -> None:
        self.runtime_events: list[dict[str, Any]] = []

    def record_runtime_event(self, **kwargs: Any) -> int:
        self.runtime_events.append(dict(kwargs))
        return len(self.runtime_events)


@pytest.mark.asyncio
async def test_agent_loop_applies_safety_for_non_hardware_channel(tmp_path: Path) -> None:
    bus = MessageBus()
    lifelog = _FakeLifelogService()
    loop = AgentLoop(
        bus=bus,
        provider=_FakeProvider("请继续直行"),
        workspace=tmp_path,
        safety_policy=_FakeSafetyPolicy(),
        lifelog_service=lifelog,
    )
    result = await loop.process_direct(
        "hello",
        session_key="cli:test-safety",
        channel="cli",
        chat_id="chat-1",
    )
    assert result.startswith("safe:")
    assert any(
        str(event.get("event_type")) == "safety_policy"
        and str((event.get("payload") or {}).get("source")) == "agent_reply"
        for event in lifelog.runtime_events
    )


@pytest.mark.asyncio
async def test_agent_loop_skips_safety_for_hardware_channel(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_FakeProvider("请继续直行"),
        workspace=tmp_path,
        safety_policy=_FakeSafetyPolicy(),
    )
    result = await loop.process_direct(
        "hello",
        session_key="hw:test-safety",
        channel="hardware",
        chat_id="device-1",
    )
    assert result == "请继续直行"


@pytest.mark.asyncio
async def test_agent_loop_no_tool_used_token_not_modified(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_FakeProvider("plain answer"),
        workspace=tmp_path,
        safety_policy=_FakeSafetyPolicy(),
    )
    result = await loop.process_direct(
        "test",
        session_key="cli:test-no-tool",
        channel="cli",
        chat_id="chat-2",
        allowed_tool_names={"web_search"},
        require_tool_use=True,
    )
    assert result == "NO_TOOL_USED"


@pytest.mark.asyncio
async def test_agent_loop_message_tool_outbound_is_safety_filtered(tmp_path: Path) -> None:
    bus = MessageBus()
    lifelog = _FakeLifelogService()
    loop = AgentLoop(
        bus=bus,
        provider=_FakeToolCallProvider(),
        workspace=tmp_path,
        safety_policy=_FakeSafetyPolicy(),
        lifelog_service=lifelog,
    )
    result = await loop.process_direct(
        "notify user",
        session_key="cli:test-msg-tool",
        channel="cli",
        chat_id="chat-99",
    )
    assert result.startswith("safe:")
    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert outbound.channel == "cli"
    assert outbound.chat_id == "chat-99"
    assert outbound.content.startswith("safe:")
    assert any(
        str(event.get("event_type")) == "safety_policy"
        and str((event.get("payload") or {}).get("source")) == "message_tool"
        for event in lifelog.runtime_events
    )


@pytest.mark.asyncio
async def test_agent_loop_process_direct_injects_runtime_context_block(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = _CaptureProvider()
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
    )
    result = await loop.process_direct(
        "hello",
        session_key="hardware:dev-1:sess-1",
        channel="hardware",
        chat_id="dev-1",
        message_metadata={
            "runtime_context": {
                "device_id": "dev-1",
                "session_id": "sess-1",
                "state": "thinking",
                "trace_id": "trace-ctx-1",
                "telemetry": {"battery": 66},
            }
        },
    )
    assert result == "ok"
    assert provider.last_messages
    system_prompt = str(provider.last_messages[0].get("content") or "")
    assert "Device Runtime Context" in system_prompt
    assert "device_id: dev-1" in system_prompt
    assert "trace_id: trace-ctx-1" in system_prompt
    assert "battery" in system_prompt

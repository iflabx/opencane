from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.agent.tools.base import Tool
from opencane.bus.events import InboundMessage
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _DoubleSpawnProvider(LLMProvider):
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
                        id="spawn-1",
                        name="spawn",
                        arguments={"task": "first"},
                    ),
                    ToolCallRequest(
                        id="spawn-2",
                        name="spawn",
                        arguments={"task": "second"},
                    ),
                ],
            )
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


class _SingleSpawnProvider(LLMProvider):
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
                        id="spawn-system",
                        name="spawn",
                        arguments={"task": "loop"},
                    )
                ],
            )
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


class _SingleExecProvider(LLMProvider):
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
                        id="exec-1",
                        name="exec",
                        arguments={"command": "pwd"},
                    )
                ],
            )
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


class _FakeSpawnTool(Tool):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return "fake spawn"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
            },
            "required": ["task"],
        }

    async def execute(self, **kwargs: Any) -> str:
        del kwargs
        self.calls += 1
        return "spawned"


class _FakeExecTool(Tool):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "fake exec"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> str:
        del kwargs
        self.calls += 1
        return "ok"


@pytest.mark.asyncio
async def test_spawn_tool_is_guarded_by_max_calls_per_turn(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_DoubleSpawnProvider(),
        workspace=tmp_path,
    )
    fake_spawn = _FakeSpawnTool()
    loop.tools.register(fake_spawn)

    result = await loop.process_direct(
        "test",
        session_key="cli:test-spawn-guard",
        channel="cli",
        chat_id="chat-guard",
    )
    assert result == "done"
    assert fake_spawn.calls == 1


@pytest.mark.asyncio
async def test_spawn_tool_is_blocked_in_system_context(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_SingleSpawnProvider(),
        workspace=tmp_path,
    )
    fake_spawn = _FakeSpawnTool()
    loop.tools.register(fake_spawn)

    outbound = await loop._process_system_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:chat-system",
            content="system update",
        )
    )
    assert outbound is not None
    assert outbound.channel == "cli"
    assert fake_spawn.calls == 0


@pytest.mark.asyncio
async def test_explicit_allowlist_still_respects_channel_policy(tmp_path: Path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_SingleExecProvider(),
        workspace=tmp_path,
    )
    fake_exec = _FakeExecTool()
    loop.tools.register(fake_exec)

    result = await loop.process_direct(
        "run tool",
        session_key="hardware:test-exec-policy",
        channel="hardware",
        chat_id="device-1",
        allowed_tool_names={"exec"},
    )
    assert result == "done"
    assert fake_exec.calls == 0

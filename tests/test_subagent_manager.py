from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.subagent import SubagentManager
from opencane.bus.queue import MessageBus
from opencane.config.schema import ExecToolConfig
from opencane.providers.base import LLMProvider, LLMResponse


class _DummyProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


class _ToolCaptureProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.tool_names: list[str] = []

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, model, max_tokens, temperature
        self.tool_names = []
        for item in tools or []:
            function = item.get("function") if isinstance(item, dict) else None
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str):
                    self.tool_names.append(name)
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_subagent_manager_enforces_running_limit(tmp_path: Path) -> None:
    manager = SubagentManager(
        provider=_DummyProvider(),
        workspace=tmp_path,
        bus=MessageBus(),
        max_running_tasks=1,
    )
    gate = asyncio.Event()

    async def _hold(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        await gate.wait()

    manager._run_subagent = _hold  # type: ignore[method-assign]

    first = await manager.spawn("first task")
    second = await manager.spawn("second task")

    assert "started" in first
    assert "limit reached" in second.lower()
    assert manager.get_running_count() == 1

    gate.set()
    await asyncio.sleep(0.05)
    assert manager.get_running_count() == 0


@pytest.mark.asyncio
async def test_subagent_manager_omits_exec_tool_when_disabled(tmp_path: Path) -> None:
    provider = _ToolCaptureProvider()
    manager = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        exec_config=ExecToolConfig(enable=False),
    )

    await manager._run_subagent(
        task_id="task-1",
        task="check tools",
        label="check tools",
        origin={"channel": "cli", "chat_id": "direct"},
    )

    assert "exec" not in provider.tool_names

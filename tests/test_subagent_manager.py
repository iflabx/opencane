from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


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

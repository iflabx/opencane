from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opencane.agent.loop import AgentLoop
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse


class _ConsolidationProvider(LLMProvider):
    def __init__(self, payload: str) -> None:
        super().__init__(api_key="test")
        self.payload = payload

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        return LLMResponse(content=self.payload)

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_consolidation_converts_non_string_history_and_memory_values(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "history_entry": {"timestamp": "2026-03-21 12:10", "summary": "User asked about routes"},
            "memory_update": {"facts": ["Prefers short guidance", "Uses EC600 module"]},
        },
        ensure_ascii=False,
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_ConsolidationProvider(payload),
        workspace=tmp_path,
        memory_window=10,
    )

    session = loop.sessions.get_or_create("cli:memory-types")
    session.add_message("user", "Hello")
    session.add_message("assistant", "Hi")

    await loop._consolidate_memory(session, archive_all=True)

    history_content = (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    memory_content = (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    assert '"summary": "User asked about routes"' in history_content
    assert '"facts": ["Prefers short guidance", "Uses EC600 module"]' in memory_content

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
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
        return LLMResponse(content="收到")

    def get_default_model(self) -> str:
        return "fake"


@pytest.mark.asyncio
async def test_agent_loop_process_direct_records_layered_memory(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
    )

    result = await loop.process_direct(
        "我喜欢咖啡",
        session_key="cli:layered-1",
        channel="cli",
        chat_id="chat-layered",
    )
    assert result == "收到"

    memory_dir = tmp_path / "memory"
    assert (memory_dir / "PROFILE.json").exists()
    assert (memory_dir / "SEMANTIC.json").exists()
    assert (memory_dir / "EPISODIC.jsonl").exists()

    semantic = (memory_dir / "SEMANTIC.json").read_text(encoding="utf-8")
    episodic = (memory_dir / "EPISODIC.jsonl").read_text(encoding="utf-8")
    assert "咖啡" in semantic
    assert "我喜欢咖啡" in episodic

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opencane.agent.subagent import SubagentManager
from opencane.bus.queue import MessageBus
from opencane.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _WriteFileSubagentProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.turn = 0

    async def chat(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del messages, tools, model, max_tokens, temperature
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="Preparing file",
                tool_calls=[
                    ToolCallRequest(
                        id="write-1",
                        name="write_file",
                        arguments={"path": "relative-subagent.txt", "content": "from-subagent"},
                    )
                ],
            )
        return LLMResponse(content="done")

    def get_default_model(self) -> str:
        return "fake-model"


@pytest.mark.asyncio
async def test_subagent_file_tools_resolve_relative_paths_to_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    monkeypatch.chdir(outside)

    manager = SubagentManager(
        provider=_WriteFileSubagentProvider(),
        workspace=workspace,
        bus=MessageBus(),
    )

    await manager._run_subagent(
        task_id="t1",
        task="write a file",
        label="write file",
        origin={"channel": "cli", "chat_id": "chat-1"},
    )

    assert (workspace / "relative-subagent.txt").read_text(encoding="utf-8") == "from-subagent"
    assert not (outside / "relative-subagent.txt").exists()

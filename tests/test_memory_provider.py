from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import UnifiedMemoryProvider


class _FakeLifelog:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(payload))
        if str(payload.get("session_id")) != "sess-42":
            return {"success": True, "hits": []}
        return {
            "success": True,
            "hits": [
                {
                    "text": "前方有台阶",
                    "score": 0.88,
                    "metadata": {"session_id": "sess-42", "ts": "2026-02-18T12:00:00Z"},
                    "structured_context": {"actionable_summary": "靠右慢行并避让台阶"},
                }
            ],
        }


class _ErrorLifelog:
    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        raise RuntimeError("boom")


def test_unified_memory_provider_file_store_compat(tmp_path: Path) -> None:
    provider = UnifiedMemoryProvider(tmp_path)
    assert provider.get_file_memory_context() == ""

    provider.write_long_term("user likes tea")
    assert provider.read_long_term() == "user likes tea"
    assert "user likes tea" in provider.get_file_memory_context()

    provider.append_history("chat summary")
    history_path = tmp_path / "memory" / "HISTORY.md"
    assert history_path.exists()
    assert "chat summary" in history_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_unified_memory_provider_retrieval_hardware_session_mapping(tmp_path: Path) -> None:
    lifelog = _FakeLifelog()
    provider = UnifiedMemoryProvider(tmp_path, lifelog_service=lifelog)
    result = await provider.retrieve_context(
        query="台阶在哪",
        session_key="hardware:device-a:sess-42",
        channel="hardware",
        chat_id="chat-fallback",
    )
    assert "Retrieved Lifelog Memory" in result
    assert "前方有台阶" in result
    assert lifelog.calls
    assert lifelog.calls[0]["session_id"] == "sess-42"


@pytest.mark.asyncio
async def test_unified_memory_provider_retrieval_graceful_on_missing_or_error(tmp_path: Path) -> None:
    without_lifelog = UnifiedMemoryProvider(tmp_path)
    no_service = await without_lifelog.retrieve_context(
        query="anything",
        session_key="cli:test",
        channel="cli",
        chat_id="chat-1",
    )
    assert no_service == ""

    with_error = UnifiedMemoryProvider(tmp_path, lifelog_service=_ErrorLifelog())
    errored = await with_error.retrieve_context(
        query="anything",
        session_key="cli:test",
        channel="cli",
        chat_id="chat-1",
    )
    assert errored == ""


def test_context_builder_uses_memory_context_override(tmp_path: Path) -> None:
    provider = UnifiedMemoryProvider(tmp_path)
    provider.write_long_term("should not appear")
    builder = ContextBuilder(tmp_path, memory_provider=provider)
    messages = builder.build_messages(
        history=[],
        current_message="hello",
        memory_context_override="## Retrieved Lifelog Memory\n- [1] custom",
    )
    system_prompt = str(messages[0]["content"])
    assert "Retrieved Lifelog Memory" in system_prompt
    assert "should not appear" not in system_prompt


@pytest.mark.asyncio
async def test_unified_memory_provider_record_turn_builds_layered_memory(tmp_path: Path) -> None:
    provider = UnifiedMemoryProvider(
        tmp_path,
        local_semantic_top_k=3,
        local_episodic_top_k=3,
        episodic_max_items=10,
        semantic_max_items=10,
    )
    provider.record_turn(
        session_key="cli:chat-1",
        channel="cli",
        chat_id="chat-1",
        user_text="我喜欢红茶，叫我小王。",
        assistant_text="收到，我记住了。",
        tools_used=["web_search"],
    )
    context = await provider.retrieve_context(
        query="红茶",
        session_key="cli:chat-1",
        channel="cli",
        chat_id="chat-1",
    )
    assert "Layered Memory (Semantic)" in context
    assert "Layered Memory (Episodic)" in context
    assert "红茶" in context

    profile = provider.file_store.read_profile()
    assert profile.get("channels", {}).get("cli") == 1
    assert "chat-1" in profile.get("chats", {})


def test_unified_memory_provider_record_turn_applies_retention(tmp_path: Path) -> None:
    provider = UnifiedMemoryProvider(
        tmp_path,
        episodic_max_items=20,
        episodic_ttl_days=365,
    )
    for idx in range(25):
        provider.record_turn(
            session_key="cli:chat-2",
            channel="cli",
            chat_id="chat-2",
            user_text=f"turn-{idx}",
            assistant_text=f"ok-{idx}",
            tools_used=[],
        )

    episodic = provider.file_store.list_episodic(limit=100)
    assert len(episodic) == 20
    joined = "\\n".join(str(item.get("user") or "") for item in episodic)
    assert "turn-0" not in joined

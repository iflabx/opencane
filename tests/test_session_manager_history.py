from opencane.session.manager import Session


def _assert_no_orphans(history: list[dict]) -> None:
    declared = {
        tc["id"]
        for m in history
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
        if isinstance(tc, dict) and tc.get("id")
    }
    orphans = [
        m.get("tool_call_id")
        for m in history
        if m.get("role") == "tool" and m.get("tool_call_id") not in declared
    ]
    assert orphans == []


def _tool_turn(prefix: str, idx: int) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": f"{prefix}_{idx}_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": f"{prefix}_{idx}_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_a", "name": "x", "content": "ok"},
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_b", "name": "y", "content": "ok"},
    ]


def test_get_history_drops_orphan_tool_results_when_window_cuts_tool_calls() -> None:
    session = Session(key="cli:test")
    session.messages.append({"role": "user", "content": "old turn"})
    for i in range(20):
        session.messages.extend(_tool_turn("old", i))
    session.messages.append({"role": "user", "content": "new turn"})
    for i in range(25):
        session.messages.extend(_tool_turn("cur", i))
    session.messages.append({"role": "user", "content": "latest question"})

    history = session.get_history(max_messages=100)
    _assert_no_orphans(history)


def test_get_history_keeps_valid_tool_pairs() -> None:
    session = Session(key="cli:test2")
    session.messages.append({"role": "user", "content": "start"})
    for i in range(4):
        session.messages.extend(_tool_turn("ok", i))
    history = session.get_history(max_messages=500)

    _assert_no_orphans(history)
    assert any(m.get("role") == "tool" for m in history)


def test_legitimate_tool_pairs_preserved_after_trim() -> None:
    session = Session(key="cli:positive")
    session.messages.append({"role": "user", "content": "hello"})
    for i in range(5):
        session.messages.extend(_tool_turn("keep", i))
    session.messages.append({"role": "assistant", "content": "done"})

    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    tool_ids = [m["tool_call_id"] for m in history if m.get("role") == "tool"]
    assert len(tool_ids) == 10
    assert history[0]["role"] == "user"


def test_orphan_trim_with_last_consolidated() -> None:
    session = Session(key="cli:consolidated")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"old {i}"})
        session.messages.extend(_tool_turn("old", i))
    session.last_consolidated = 30

    session.messages.append({"role": "user", "content": "recent"})
    for i in range(15):
        session.messages.extend(_tool_turn("new", i))
    session.messages.append({"role": "user", "content": "latest"})

    history = session.get_history(max_messages=20)
    _assert_no_orphans(history)
    assert all(
        m.get("role") != "tool" or str(m.get("tool_call_id", "")).startswith("new_")
        for m in history
    )


def test_no_tool_messages_unchanged() -> None:
    session = Session(key="cli:plain")
    for i in range(5):
        session.messages.append({"role": "user", "content": f"q{i}"})
        session.messages.append({"role": "assistant", "content": f"a{i}"})

    history = session.get_history(max_messages=6)
    _assert_no_orphans(history)
    assert len(history) == 6


def test_all_orphan_prefix_stripped() -> None:
    session = Session(key="cli:all-orphan")
    session.messages.append({"role": "tool", "tool_call_id": "gone_1", "name": "x", "content": "ok"})
    session.messages.append({"role": "tool", "tool_call_id": "gone_2", "name": "y", "content": "ok"})
    session.messages.append({"role": "user", "content": "fresh start"})
    session.messages.append({"role": "assistant", "content": "hi"})

    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    assert history[0]["role"] == "user"
    assert len(history) == 2


def test_empty_session_history() -> None:
    session = Session(key="cli:empty")
    history = session.get_history(max_messages=500)
    assert history == []


def test_window_cuts_mid_tool_group() -> None:
    session = Session(key="cli:mid-cut")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "split_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "split_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        }
    )
    session.messages.append({"role": "tool", "tool_call_id": "split_a", "name": "x", "content": "ok"})
    session.messages.append({"role": "tool", "tool_call_id": "split_b", "name": "y", "content": "ok"})
    session.messages.append({"role": "user", "content": "next"})
    session.messages.extend(_tool_turn("intact", 0))
    session.messages.append({"role": "assistant", "content": "final"})

    history = session.get_history(max_messages=6)
    _assert_no_orphans(history)

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


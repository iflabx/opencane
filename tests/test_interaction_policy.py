from opencane.safety.interaction_policy import InteractionPolicy


def test_interaction_policy_adds_emotion_prefix_for_high_risk() -> None:
    policy = InteractionPolicy(
        enabled=True,
        emotion_enabled=True,
        proactive_enabled=False,
        silent_enabled=False,
        high_risk_levels=["P0", "P1"],
    )
    decision = policy.evaluate(
        text="前方可能有车辆。",
        source="vision_reply",
        confidence=0.92,
        risk_level="P1",
        context={},
        speak=True,
    )
    assert decision.should_speak is True
    assert decision.text.startswith("请先停下，注意安全。")
    assert "emotion_high_risk_prefix" in decision.flags


def test_interaction_policy_appends_proactive_hint() -> None:
    policy = InteractionPolicy(
        enabled=True,
        emotion_enabled=False,
        proactive_enabled=True,
        silent_enabled=False,
        proactive_sources=["vision_reply"],
    )
    decision = policy.evaluate(
        text="前方是楼梯口。",
        source="vision_reply",
        confidence=0.9,
        risk_level="P2",
        context={"proactive_hint": "如需我可以继续描述左侧障碍。"},
        speak=True,
    )
    assert decision.should_speak is True
    assert "如需我可以继续描述左侧障碍。" in decision.text
    assert "proactive_hint_appended" in decision.flags


def test_interaction_policy_silence_low_priority_in_quiet_hours() -> None:
    policy = InteractionPolicy(
        enabled=True,
        emotion_enabled=False,
        proactive_enabled=False,
        silent_enabled=True,
        silent_sources=["task_update"],
        quiet_hours_enabled=True,
        quiet_hours_start_hour=23,
        quiet_hours_end_hour=7,
        suppress_low_priority_in_quiet_hours=True,
        current_hour_fn=lambda: 23,
    )
    decision = policy.evaluate(
        text="任务还在执行中。",
        source="task_update",
        confidence=1.0,
        risk_level="P3",
        context={"priority": "low"},
        speak=True,
    )
    assert decision.should_speak is False
    assert decision.reason in {"silent_low_priority", "silent_quiet_hours"}
    assert any(flag.startswith("silent_") for flag in decision.flags)

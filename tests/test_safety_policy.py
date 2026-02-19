from nanobot.safety.policy import SafetyPolicy


def test_safety_policy_low_confidence_downgrade() -> None:
    policy = SafetyPolicy(
        enabled=True,
        low_confidence_threshold=0.8,
        max_output_chars=300,
    )
    decision = policy.evaluate(
        text="请向前走10米，然后左转。",
        source="vision_reply",
        confidence=0.2,
        risk_level="P1",
    )
    assert decision.downgraded is True
    assert decision.reason == "low_confidence"
    assert decision.risk_level == "P1"
    assert "请先停下" in decision.text


def test_safety_policy_infer_risk_and_add_caution_prefix() -> None:
    policy = SafetyPolicy(
        enabled=True,
        low_confidence_threshold=0.4,
        max_output_chars=300,
        prepend_caution_for_risk=True,
    )
    decision = policy.evaluate(
        text="前方有车流，请注意观察。",
        source="vision_reply",
        confidence=0.95,
    )
    assert decision.downgraded is False
    assert decision.risk_level == "P0"
    assert decision.text.startswith("注意安全。")
    assert "caution_prefix_added" in decision.flags


def test_safety_policy_disabled_passthrough_with_truncation() -> None:
    policy = SafetyPolicy(
        enabled=False,
        low_confidence_threshold=0.99,
        max_output_chars=20,
    )
    text = "0123456789" * 12
    decision = policy.evaluate(
        text=text,
        source="task_update",
        confidence=0.1,
        risk_level="P0",
    )
    assert decision.downgraded is False
    assert decision.reason == "ok"
    assert decision.text.endswith("...")
    assert len(decision.text) <= 64

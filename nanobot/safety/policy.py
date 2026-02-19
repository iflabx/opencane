"""Safety policy engine for runtime speech/text outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_RISK_ORDER = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
}
_P0_KEYWORDS = (
    "车流",
    "来车",
    "机动车",
    "高速",
    "火灾",
    "煤气",
    "触电",
    "深坑",
    "坠落",
    "gas leak",
    "fire",
)
_P1_KEYWORDS = (
    "楼梯",
    "台阶",
    "路口",
    "斑马线",
    "施工",
    "障碍",
    "人群",
    "路沿",
    "stairs",
    "crosswalk",
    "intersection",
)
_P2_KEYWORDS = (
    "可能",
    "不确定",
    "模糊",
    "大概",
    "perhaps",
    "uncertain",
    "maybe",
)
_DIRECTIONAL_KEYWORDS = (
    "向前",
    "前进",
    "直行",
    "左转",
    "右转",
    "go straight",
    "turn left",
    "turn right",
)


def _normalize_risk(value: Any, default: str = "P3") -> str:
    text = str(value or "").strip().upper()
    return text if text in _RISK_ORDER else default


def _higher_risk(left: str, right: str) -> str:
    return left if _RISK_ORDER[left] <= _RISK_ORDER[right] else right


def _clamp_confidence(value: Any, default: float = 1.0) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        conf = float(default)
    return max(0.0, min(1.0, conf))


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any((kw in text) or (kw in lower) for kw in keywords)


def _contains_directional_instruction(text: str) -> bool:
    return _contains_keyword(text, _DIRECTIONAL_KEYWORDS)


def _has_conflicting_directions(text: str) -> bool:
    lower = text.lower()
    has_left = ("左转" in text) or ("turn left" in lower)
    has_right = ("右转" in text) or ("turn right" in lower)
    return has_left and has_right


def _has_caution_prefix(text: str) -> bool:
    prefixes = (
        "注意",
        "小心",
        "请先停",
        "先停",
        "请立即停",
        "caution",
        "warning",
    )
    lower = text.lower()
    return any(lower.startswith(p.lower()) for p in prefixes)


def _shorten(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


@dataclass(slots=True)
class SafetyDecision:
    """Safety decision for one outbound text."""

    text: str
    source: str
    risk_level: str
    confidence: float
    downgraded: bool
    reason: str
    flags: list[str]
    policy_version: str
    rule_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "downgraded": self.downgraded,
            "reason": self.reason,
            "flags": list(self.flags),
            "policy_version": self.policy_version,
            "rule_ids": list(self.rule_ids),
            "evidence": dict(self.evidence),
        }


class SafetyPolicy:
    """Rule-based policy for safer, conservative runtime output."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        low_confidence_threshold: float = 0.55,
        max_output_chars: int = 320,
        prepend_caution_for_risk: bool = True,
        semantic_guard_enabled: bool = True,
        directional_confidence_threshold: float = 0.85,
    ) -> None:
        self.enabled = bool(enabled)
        self.low_confidence_threshold = _clamp_confidence(low_confidence_threshold, default=0.55)
        self.max_output_chars = max(64, int(max_output_chars))
        self.prepend_caution_for_risk = bool(prepend_caution_for_risk)
        self.semantic_guard_enabled = bool(semantic_guard_enabled)
        self.directional_confidence_threshold = _clamp_confidence(
            directional_confidence_threshold,
            default=0.85,
        )

    @classmethod
    def from_config(cls, config: Any) -> "SafetyPolicy":
        cfg = getattr(config, "safety", None)
        if cfg is None:
            return cls()
        return cls(
            enabled=bool(getattr(cfg, "enabled", True)),
            low_confidence_threshold=_clamp_confidence(
                getattr(cfg, "low_confidence_threshold", 0.55),
                default=0.55,
            ),
            max_output_chars=max(64, int(getattr(cfg, "max_output_chars", 320))),
            prepend_caution_for_risk=bool(getattr(cfg, "prepend_caution_for_risk", True)),
            semantic_guard_enabled=bool(getattr(cfg, "semantic_guard_enabled", True)),
            directional_confidence_threshold=_clamp_confidence(
                getattr(cfg, "directional_confidence_threshold", 0.85),
                default=0.85,
            ),
        )

    def evaluate(
        self,
        *,
        text: str,
        source: str,
        confidence: float | None = None,
        risk_level: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SafetyDecision:
        raw_text = str(text or "").strip()
        out = raw_text
        source_name = str(source or "runtime").strip() or "runtime"
        conf = _clamp_confidence(confidence, default=1.0)
        inferred = self._infer_risk(raw_text, context=context or {})
        risk = _higher_risk(_normalize_risk(risk_level, default="P3"), inferred)

        flags: list[str] = []
        rule_ids: list[str] = []
        downgraded = False
        reason = "ok"
        evidence = {
            "input_risk_level": _normalize_risk(risk_level, default="P3"),
            "inferred_risk_level": inferred,
            "directional": _contains_directional_instruction(raw_text),
            "conflict_direction": _has_conflicting_directions(raw_text),
        }

        if not out:
            out = self._fallback_message(risk)
            flags.append("empty_output")
            rule_ids.append("empty_output")
            downgraded = True
            reason = "empty_output"

        if self.enabled:
            if conf < self.low_confidence_threshold:
                out = self._fallback_message(risk)
                flags.append("low_confidence")
                rule_ids.append("low_confidence")
                downgraded = True
                reason = "low_confidence"
            elif self.prepend_caution_for_risk and risk in {"P0", "P1"} and out and not _has_caution_prefix(out):
                out = f"注意安全。{out}"
                flags.append("caution_prefix_added")
                rule_ids.append("caution_prefix_added")

            if self.semantic_guard_enabled and not downgraded:
                if _has_conflicting_directions(out):
                    out = self._fallback_message(risk)
                    flags.append("semantic_guard_conflict")
                    rule_ids.append("semantic_guard_conflict")
                    downgraded = True
                    reason = "semantic_guard_conflict"
                elif (
                    risk in {"P0", "P1"}
                    and conf < self.directional_confidence_threshold
                    and _contains_directional_instruction(out)
                ):
                    out = self._fallback_message(risk)
                    flags.append("semantic_guard_directional")
                    rule_ids.append("semantic_guard_directional")
                    downgraded = True
                    reason = "semantic_guard_directional"

        if len(out) > self.max_output_chars:
            out = _shorten(out, self.max_output_chars)
            flags.append("output_truncated")
            rule_ids.append("output_truncated")

        return SafetyDecision(
            text=out,
            source=source_name,
            risk_level=risk,
            confidence=conf,
            downgraded=downgraded,
            reason=reason,
            flags=flags,
            policy_version="v1.1",
            rule_ids=rule_ids,
            evidence=evidence,
        )

    def _infer_risk(self, text: str, *, context: dict[str, Any]) -> str:
        risk = _normalize_risk(context.get("risk_level"), default="P3")
        if _contains_keyword(text, _P0_KEYWORDS):
            risk = _higher_risk(risk, "P0")
        elif _contains_keyword(text, _P1_KEYWORDS):
            risk = _higher_risk(risk, "P1")
        elif _contains_keyword(text, _P2_KEYWORDS):
            risk = _higher_risk(risk, "P2")
        return risk

    @staticmethod
    def _fallback_message(risk_level: str) -> str:
        risk = _normalize_risk(risk_level)
        if risk == "P0":
            return "我对当前环境判断不够确定。请立即停下，先确认周边安全并寻求附近人员协助。"
        if risk == "P1":
            return "我当前判断不够稳定。请先停下，用盲杖确认前方，再谨慎移动。"
        return "我现在不够确定。请先停下并确认周边环境安全。"

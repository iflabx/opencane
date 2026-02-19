"""Interaction policy engine for emotion/proactive/silent runtime behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


def _normalize_risk(value: Any, default: str = "P3") -> str:
    text = str(value or "").strip().upper()
    return text if text in {"P0", "P1", "P2", "P3"} else default


def _clamp_confidence(value: Any, default: float = 1.0) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        conf = float(default)
    return max(0.0, min(1.0, conf))


def _starts_with_any(text: str, prefixes: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(lower.startswith(p.lower()) for p in prefixes)


def _shorten(text: str, max_chars: int = 80) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


@dataclass(slots=True)
class InteractionDecision:
    """Interaction policy decision for one outbound message."""

    text: str
    should_speak: bool
    source: str
    risk_level: str
    confidence: float
    reason: str
    flags: list[str] = field(default_factory=list)
    policy_version: str = "v1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "should_speak": self.should_speak,
            "source": self.source,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "reason": self.reason,
            "flags": list(self.flags),
            "policy_version": self.policy_version,
        }


class InteractionPolicy:
    """Rule-based strategy for emotion tone, proactive hints, and silence control."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        emotion_enabled: bool = True,
        proactive_enabled: bool = True,
        silent_enabled: bool = True,
        low_confidence_threshold: float = 0.45,
        high_risk_levels: list[str] | None = None,
        proactive_sources: list[str] | None = None,
        silent_sources: list[str] | None = None,
        quiet_hours_enabled: bool = False,
        quiet_hours_start_hour: int = 23,
        quiet_hours_end_hour: int = 7,
        suppress_low_priority_in_quiet_hours: bool = True,
        current_hour_fn: Callable[[], int] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.emotion_enabled = bool(emotion_enabled)
        self.proactive_enabled = bool(proactive_enabled)
        self.silent_enabled = bool(silent_enabled)
        self.low_confidence_threshold = _clamp_confidence(low_confidence_threshold, default=0.45)
        self.high_risk_levels = {
            _normalize_risk(item, default="")
            for item in (high_risk_levels or ["P0", "P1"])
            if _normalize_risk(item, default="")
        }
        self.proactive_sources = {
            str(item).strip().lower()
            for item in (proactive_sources or ["vision_reply"])
            if str(item).strip()
        }
        self.silent_sources = {
            str(item).strip().lower()
            for item in (silent_sources or ["task_update"])
            if str(item).strip()
        }
        self.quiet_hours_enabled = bool(quiet_hours_enabled)
        self.quiet_hours_start_hour = int(quiet_hours_start_hour) % 24
        self.quiet_hours_end_hour = int(quiet_hours_end_hour) % 24
        self.suppress_low_priority_in_quiet_hours = bool(suppress_low_priority_in_quiet_hours)
        self._current_hour_fn = current_hour_fn or (lambda: datetime.now().hour)

    @classmethod
    def from_config(cls, config: Any) -> "InteractionPolicy":
        cfg = getattr(config, "interaction", None)
        if cfg is None:
            return cls()
        return cls(
            enabled=bool(getattr(cfg, "enabled", True)),
            emotion_enabled=bool(getattr(cfg, "emotion_enabled", True)),
            proactive_enabled=bool(getattr(cfg, "proactive_enabled", True)),
            silent_enabled=bool(getattr(cfg, "silent_enabled", True)),
            low_confidence_threshold=_clamp_confidence(
                getattr(cfg, "low_confidence_threshold", 0.45),
                default=0.45,
            ),
            high_risk_levels=list(getattr(cfg, "high_risk_levels", ["P0", "P1"]) or []),
            proactive_sources=list(getattr(cfg, "proactive_sources", ["vision_reply"]) or []),
            silent_sources=list(getattr(cfg, "silent_sources", ["task_update"]) or []),
            quiet_hours_enabled=bool(getattr(cfg, "quiet_hours_enabled", False)),
            quiet_hours_start_hour=int(getattr(cfg, "quiet_hours_start_hour", 23)),
            quiet_hours_end_hour=int(getattr(cfg, "quiet_hours_end_hour", 7)),
            suppress_low_priority_in_quiet_hours=bool(
                getattr(cfg, "suppress_low_priority_in_quiet_hours", True)
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
        speak: bool = True,
    ) -> InteractionDecision:
        original = str(text or "").strip()
        source_name = str(source or "runtime").strip() or "runtime"
        source_lower = source_name.lower()
        conf = _clamp_confidence(confidence, default=1.0)
        risk = _normalize_risk(risk_level, default="P3")
        ctx = context if isinstance(context, dict) else {}
        out = original
        should_speak = bool(speak)
        reason = "ok"
        flags: list[str] = []

        if not self.enabled:
            return InteractionDecision(
                text=out,
                should_speak=should_speak,
                source=source_name,
                risk_level=risk,
                confidence=conf,
                reason="disabled",
                flags=flags,
            )

        if self.silent_enabled and should_speak:
            priority = str(ctx.get("priority") or "").strip().lower()
            if source_lower in self.silent_sources and priority == "low":
                should_speak = False
                reason = "silent_low_priority"
                flags.append("silent_low_priority")
            elif (
                self.quiet_hours_enabled
                and self.suppress_low_priority_in_quiet_hours
                and self._in_quiet_hours()
                and source_lower in self.silent_sources
                and priority in {"", "low", "normal"}
                and risk not in self.high_risk_levels
            ):
                should_speak = False
                reason = "silent_quiet_hours"
                flags.append("silent_quiet_hours")

        if out and self.emotion_enabled:
            if risk in self.high_risk_levels and not _starts_with_any(out, ("注意", "小心", "请先停", "warning", "caution")):
                out = f"请先停下，注意安全。{out}"
                flags.append("emotion_high_risk_prefix")
            elif conf < self.low_confidence_threshold and not _starts_with_any(out, ("我不太确定", "不太确定", "i may be wrong", "not fully sure")):
                out = f"我不太确定，建议先确认周边环境。{out}"
                flags.append("emotion_low_confidence_prefix")

        if out and self.proactive_enabled and source_lower in self.proactive_sources:
            proactive_hint = str(ctx.get("proactive_hint") or "").strip()
            if proactive_hint:
                out = f"{out} {_shorten(proactive_hint, 72)}"
                flags.append("proactive_hint_appended")

        return InteractionDecision(
            text=out,
            should_speak=should_speak,
            source=source_name,
            risk_level=risk,
            confidence=conf,
            reason=reason,
            flags=flags,
        )

    def _in_quiet_hours(self) -> bool:
        start = self.quiet_hours_start_hour
        end = self.quiet_hours_end_hour
        now_hour = int(self._current_hour_fn()) % 24
        if start == end:
            return True
        if start < end:
            return start <= now_hour < end
        return now_hour >= start or now_hour < end

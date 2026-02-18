"""Runtime observability helpers for hardware flows."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class HardwareRuntimeMetrics:
    """In-memory counters for hardware runtime observability."""

    started_at_ms: int = field(default_factory=now_ms)
    events_total: int = 0
    commands_total: int = 0
    duplicate_events_total: int = 0
    events_by_type: Counter[str] = field(default_factory=Counter)
    commands_by_type: Counter[str] = field(default_factory=Counter)
    voice_turn_total: int = 0
    voice_turn_failed: int = 0
    voice_turn_total_latency_ms: float = 0.0
    voice_turn_max_latency_ms: float = 0.0
    stt_total_latency_ms: float = 0.0
    stt_max_latency_ms: float = 0.0
    agent_total_latency_ms: float = 0.0
    agent_max_latency_ms: float = 0.0

    def record_event(self, event_type: str) -> None:
        self.events_total += 1
        self.events_by_type[str(event_type)] += 1

    def record_command(self, command_type: str) -> None:
        self.commands_total += 1
        self.commands_by_type[str(command_type)] += 1

    def record_duplicate_event(self, event_type: str) -> None:
        self.duplicate_events_total += 1
        self.events_by_type[str(event_type)] += 0

    def record_voice_turn(
        self,
        *,
        success: bool,
        total_latency_ms: float,
        stt_latency_ms: float = 0.0,
        agent_latency_ms: float = 0.0,
    ) -> None:
        self.voice_turn_total += 1
        if not success:
            self.voice_turn_failed += 1
        total_ms = max(0.0, float(total_latency_ms))
        stt_ms = max(0.0, float(stt_latency_ms))
        agent_ms = max(0.0, float(agent_latency_ms))
        self.voice_turn_total_latency_ms += total_ms
        self.voice_turn_max_latency_ms = max(self.voice_turn_max_latency_ms, total_ms)
        self.stt_total_latency_ms += stt_ms
        self.stt_max_latency_ms = max(self.stt_max_latency_ms, stt_ms)
        self.agent_total_latency_ms += agent_ms
        self.agent_max_latency_ms = max(self.agent_max_latency_ms, agent_ms)

    def snapshot(self) -> dict[str, Any]:
        voice_total = max(0, int(self.voice_turn_total))
        return {
            "started_at_ms": self.started_at_ms,
            "events_total": self.events_total,
            "commands_total": self.commands_total,
            "duplicate_events_total": self.duplicate_events_total,
            "events_by_type": dict(self.events_by_type),
            "commands_by_type": dict(self.commands_by_type),
            "voice_turn_total": voice_total,
            "voice_turn_failed": int(self.voice_turn_failed),
            "voice_turn_avg_latency_ms": round(
                float(self.voice_turn_total_latency_ms) / float(voice_total) if voice_total > 0 else 0.0,
                2,
            ),
            "voice_turn_max_latency_ms": round(float(self.voice_turn_max_latency_ms), 2),
            "stt_avg_latency_ms": round(
                float(self.stt_total_latency_ms) / float(voice_total) if voice_total > 0 else 0.0,
                2,
            ),
            "stt_max_latency_ms": round(float(self.stt_max_latency_ms), 2),
            "agent_avg_latency_ms": round(
                float(self.agent_total_latency_ms) / float(voice_total) if voice_total > 0 else 0.0,
                2,
            ),
            "agent_max_latency_ms": round(float(self.agent_max_latency_ms), 2),
        }

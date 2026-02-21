"""Control API security helpers (rate limit and replay protection)."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_timestamp_ms(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return None
    # Allow seconds input as well.
    if parsed > 0 and parsed < 10_000_000_000:
        parsed *= 1000
    return parsed


@dataclass(slots=True)
class RequestRateLimiter:
    """Sliding-window per-key request limiter."""

    requests_per_minute: int = 600
    burst: int = 120
    window_seconds: int = 60
    _now_fn: Callable[[], int] = now_ms
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _hits: dict[str, deque[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.requests_per_minute = max(1, int(self.requests_per_minute))
        self.burst = max(0, int(self.burst))
        self.window_seconds = max(1, int(self.window_seconds))

    @property
    def limit(self) -> int:
        return int(self.requests_per_minute + self.burst)

    def allow(self, *, key: str) -> bool:
        token = str(key or "").strip() or "unknown"
        now = int(self._now_fn())
        cutoff = now - self.window_seconds * 1000
        with self._lock:
            buf = self._hits.get(token)
            if buf is None:
                buf = deque()
                self._hits[token] = buf
            while buf and int(buf[0]) < cutoff:
                buf.popleft()
            if len(buf) >= self.limit:
                return False
            buf.append(now)
            # Keep map from growing forever.
            if len(self._hits) > 10000:
                stale_keys = [k for k, q in self._hits.items() if not q or int(q[-1]) < cutoff]
                for stale in stale_keys[:2000]:
                    self._hits.pop(stale, None)
            return True


@dataclass(slots=True)
class RequestReplayProtector:
    """Nonce + timestamp validator for write requests."""

    window_seconds: int = 300
    max_entries: int = 20000
    _now_fn: Callable[[], int] = now_ms
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _seen: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.window_seconds = max(10, int(self.window_seconds))
        self.max_entries = max(1000, int(self.max_entries))

    def validate(self, *, key: str, nonce: str, timestamp_ms: int) -> tuple[bool, str]:
        token = str(key or "").strip() or "unknown"
        nonce_val = str(nonce or "").strip()
        if not nonce_val:
            return False, "missing_nonce"
        ts = int(timestamp_ms)
        now = int(self._now_fn())
        window_ms = self.window_seconds * 1000
        if abs(now - ts) > window_ms:
            return False, "stale_timestamp"

        replay_key = f"{token}:{nonce_val}"
        cutoff = now - window_ms
        with self._lock:
            seen_ts = self._seen.get(replay_key)
            if seen_ts is not None and seen_ts >= cutoff:
                return False, "replayed_nonce"
            self._seen[replay_key] = now
            # Opportunistic cleanup.
            if len(self._seen) > self.max_entries:
                stale = [k for k, v in self._seen.items() if int(v) < cutoff]
                for item in stale[: max(1000, len(stale))]:
                    self._seen.pop(item, None)
                if len(self._seen) > self.max_entries:
                    overflow = len(self._seen) - self.max_entries
                    for item in list(self._seen.keys())[:overflow]:
                        self._seen.pop(item, None)
        return True, "ok"

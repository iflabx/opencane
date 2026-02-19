"""Timeline query service for lifelog events."""

from __future__ import annotations

from nanobot.vision.store import VisionLifelogStore


class LifelogTimelineService:
    """Read-oriented facade for timeline output."""

    def __init__(self, store: VisionLifelogStore) -> None:
        self.store = store

    def list_timeline(
        self,
        *,
        session_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        event_type: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        return self.store.timeline(
            session_id=session_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type=event_type,
            risk_level=risk_level,
            limit=limit,
            offset=offset,
        )

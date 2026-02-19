from __future__ import annotations

from typing import Any

import pytest

from nanobot.cli.commands import (
    _apply_control_plane_runtime_overrides,
    _ControlPlaneRuntimeRefresher,
)


class _Runtime:
    def __init__(self) -> None:
        self.tts_mode = "device_text"
        self.no_heartbeat_timeout_s = 60


class _SafetyPolicy:
    def __init__(self) -> None:
        self.low_confidence_threshold = 0.55
        self.max_output_chars = 320


class _ControlPlaneClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def fetch_runtime_config(self, force_refresh: bool = False) -> dict[str, Any]:
        self.calls.append({"force_refresh": bool(force_refresh)})
        if not self.responses:
            return {"success": True, "source": "cache", "data": {}}
        return self.responses.pop(0)


def test_apply_control_plane_runtime_overrides_updates_runtime_and_safety() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    source, warning = _apply_control_plane_runtime_overrides(
        runtime,
        safety,
        {
            "success": True,
            "source": "remote",
            "warning": "cp-warning",
            "data": {
                "tts_mode": "server_audio",
                "no_heartbeat_timeout_s": 95,
                "safety": {
                    "low_confidence_threshold": 0.61,
                    "max_output_chars": 280,
                },
            },
        },
    )
    assert source == "remote"
    assert warning == "cp-warning"
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 95
    assert safety.low_confidence_threshold == 0.61
    assert safety.max_output_chars == 280


@pytest.mark.asyncio
async def test_control_plane_runtime_refresher_initial_and_periodic_refresh() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    now = [0.0]

    def _now() -> float:
        return now[0]

    client = _ControlPlaneClient(
        responses=[
            {
                "success": True,
                "source": "remote",
                "data": {"tts_mode": "device_text", "no_heartbeat_timeout_s": 70},
            },
            {
                "success": True,
                "source": "stale_cache",
                "warning": "cp degraded",
                "data": {"tts_mode": "server_audio", "no_heartbeat_timeout_s": 88},
            },
        ]
    )
    refresher = _ControlPlaneRuntimeRefresher(
        client=client,
        runtime=runtime,
        safety_policy=safety,
        refresh_seconds=5.0,
        now_fn=_now,
    )

    source, warning = await refresher.load_initial()
    assert source == "remote"
    assert warning == ""
    assert runtime.tts_mode == "device_text"
    assert runtime.no_heartbeat_timeout_s == 70
    assert client.calls == [{"force_refresh": False}]

    not_due = await refresher.refresh_if_due()
    assert not_due is None
    assert len(client.calls) == 1

    now[0] = 5.2
    due = await refresher.refresh_if_due()
    assert isinstance(due, dict)
    assert due["source"] == "stale_cache"
    assert due["source_changed"] is True
    assert due["warning_changed"] is True
    assert due["warning"] == "cp degraded"
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 88
    assert client.calls[-1] == {"force_refresh": True}

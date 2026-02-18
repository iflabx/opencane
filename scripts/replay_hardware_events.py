#!/usr/bin/env python3
"""Replay canonical hardware events to control API /v1/device/event."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError


def _load_scenario(path: Path) -> list[tuple[dict[str, Any], int]]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"empty scenario: {path}")

    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"scenario root must be list: {path}")
        rows = data
    else:
        rows = []
        for line in raw.splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            rows.append(json.loads(text))

    output: list[tuple[dict[str, Any], int]] = []
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"scenario row #{idx} must be object")
        event = row.get("event") if "event" in row else row
        if not isinstance(event, dict):
            raise ValueError(f"scenario row #{idx} event must be object")
        delay_ms = row.get("delay_ms", 0)
        try:
            delay = max(0, int(delay_ms))
        except (TypeError, ValueError):
            delay = 0
        output.append((event, delay))
    if not output:
        raise ValueError(f"scenario has no events: {path}")
    return output


def _request_json(
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None,
    auth_token: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    body = b""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body if payload is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            status = int(resp.status)
            data = json.loads(resp.read().decode("utf-8"))
            return status, data if isinstance(data, dict) else {"value": data}
    except HTTPError as exc:
        payload_text = exc.read().decode("utf-8", errors="ignore")
        try:
            data = json.loads(payload_text)
            if not isinstance(data, dict):
                data = {"value": data}
        except Exception:
            data = {"success": False, "error": payload_text}
        return int(exc.code), data


def _main() -> int:
    parser = argparse.ArgumentParser(description="Replay hardware events into control API")
    parser.add_argument("--base-url", default="http://127.0.0.1:18792", help="Control API base URL")
    parser.add_argument("--scenario", required=True, help="Path to scenario file (.json list or .jsonl)")
    parser.add_argument("--auth-token", default="", help="Bearer token for control API")
    parser.add_argument("--request-timeout", type=float, default=8.0, help="HTTP timeout seconds")
    parser.add_argument("--default-delay-ms", type=int, default=0, help="Delay between events if not set")
    parser.add_argument("--post-wait-ms", type=int, default=300, help="Wait after replay before status check")
    parser.add_argument("--expect-voice-turn-min", type=int, default=None, help="Expect minimum voice_turn_total")
    parser.add_argument(
        "--expect-duplicate-events-min",
        type=int,
        default=None,
        help="Expect minimum duplicate_events_total",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario).expanduser().resolve()
    rows = _load_scenario(scenario_path)
    base_url = str(args.base_url).rstrip("/")

    print(f"scenario: {scenario_path}")
    for idx, (event, delay_ms) in enumerate(rows, start=1):
        if delay_ms <= 0:
            delay_ms = max(0, int(args.default_delay_ms))
        status, data = _request_json(
            f"{base_url}/v1/device/event",
            method="POST",
            payload=event,
            auth_token=str(args.auth_token),
            timeout_seconds=float(args.request_timeout),
        )
        ok = status == 200 and bool(data.get("success"))
        print(f"[{idx}/{len(rows)}] type={event.get('type')} seq={event.get('seq')} status={status} ok={ok}")
        if not ok:
            print(f"request failed: {data}", file=sys.stderr)
            return 1
        if delay_ms > 0:
            time.sleep(float(delay_ms) / 1000.0)

    if int(args.post_wait_ms) > 0:
        time.sleep(float(int(args.post_wait_ms)) / 1000.0)

    status, data = _request_json(
        f"{base_url}/v1/runtime/status",
        method="GET",
        payload=None,
        auth_token=str(args.auth_token),
        timeout_seconds=float(args.request_timeout),
    )
    if status != 200:
        print(f"runtime status request failed: status={status} body={data}", file=sys.stderr)
        return 1

    metrics = data.get("metrics")
    metric_map = metrics if isinstance(metrics, dict) else {}
    voice_turn_total = int(metric_map.get("voice_turn_total", 0) or 0)
    duplicate_events_total = int(metric_map.get("duplicate_events_total", 0) or 0)
    print(
        "status metrics: "
        f"events_total={metric_map.get('events_total', 0)} "
        f"commands_total={metric_map.get('commands_total', 0)} "
        f"voice_turn_total={voice_turn_total} "
        f"duplicate_events_total={duplicate_events_total}"
    )

    expected_voice = args.expect_voice_turn_min
    if expected_voice is not None and voice_turn_total < int(expected_voice):
        print(
            f"expectation failed: voice_turn_total={voice_turn_total} < {int(expected_voice)}",
            file=sys.stderr,
        )
        return 2
    expected_dup = args.expect_duplicate_events_min
    if expected_dup is not None and duplicate_events_total < int(expected_dup):
        print(
            f"expectation failed: duplicate_events_total={duplicate_events_total} < {int(expected_dup)}",
            file=sys.stderr,
        )
        return 2

    print("replay completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

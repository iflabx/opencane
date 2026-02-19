from nanobot.api.control_security import (
    RequestRateLimiter,
    RequestReplayProtector,
    parse_timestamp_ms,
)


def test_parse_timestamp_ms_supports_seconds_and_milliseconds() -> None:
    assert parse_timestamp_ms("1700000000") == 1_700_000_000_000
    assert parse_timestamp_ms("1700000000000") == 1_700_000_000_000
    assert parse_timestamp_ms("bad") is None
    assert parse_timestamp_ms("") is None


def test_request_rate_limiter_blocks_after_limit() -> None:
    now = [1_700_000_000_000]
    limiter = RequestRateLimiter(
        requests_per_minute=2,
        burst=1,
        window_seconds=60,
        _now_fn=lambda: now[0],
    )
    assert limiter.allow(key="client-1") is True
    assert limiter.allow(key="client-1") is True
    assert limiter.allow(key="client-1") is True
    assert limiter.allow(key="client-1") is False

    now[0] += 61_000
    assert limiter.allow(key="client-1") is True


def test_request_replay_protector_rejects_replayed_nonce_and_stale_timestamp() -> None:
    now = [1_700_000_000_000]
    protector = RequestReplayProtector(
        window_seconds=5,
        _now_fn=lambda: now[0],
    )
    ok, reason = protector.validate(key="client-1", nonce="nonce-1", timestamp_ms=now[0])
    assert ok is True
    assert reason == "ok"

    ok, reason = protector.validate(key="client-1", nonce="nonce-1", timestamp_ms=now[0])
    assert ok is False
    assert reason == "replayed_nonce"

    ok, reason = protector.validate(key="client-1", nonce="nonce-2", timestamp_ms=now[0] - 11_000)
    assert ok is False
    assert reason == "stale_timestamp"

from concurrent.futures import TimeoutError as FutureTimeoutError
from http import HTTPStatus

from opencane.api.hardware_server import _ControlRequestHandler


def test_auth_disabled_allows_request() -> None:
    headers = {}
    assert _ControlRequestHandler._is_authorized_request(headers, enabled=False, token="")


def test_auth_enabled_accepts_bearer_token() -> None:
    headers = {"Authorization": "Bearer secret-token"}
    assert _ControlRequestHandler._is_authorized_request(
        headers,
        enabled=True,
        token="secret-token",
    )


def test_auth_enabled_accepts_x_auth_token() -> None:
    headers = {"X-Auth-Token": "secret-token"}
    assert _ControlRequestHandler._is_authorized_request(
        headers,
        enabled=True,
        token="secret-token",
    )


def test_auth_enabled_rejects_wrong_token() -> None:
    headers = {"Authorization": "Bearer wrong-token"}
    assert not _ControlRequestHandler._is_authorized_request(
        headers,
        enabled=True,
        token="secret-token",
    )


def test_auth_enabled_rejects_when_missing_token() -> None:
    headers = {}
    assert not _ControlRequestHandler._is_authorized_request(
        headers,
        enabled=True,
        token="secret-token",
    )


class _DummyFuture:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def result(self, timeout: float):  # type: ignore[no-untyped-def]
        if self.mode == "ok":
            return {"ok": True, "timeout": timeout}
        if self.mode == "timeout":
            raise FutureTimeoutError()
        raise RuntimeError("boom")


def test_resolve_future_result_success() -> None:
    ok, result, status, error = _ControlRequestHandler._resolve_future_result(
        _DummyFuture("ok"),
        timeout=1.5,
    )
    assert ok
    assert result == {"ok": True, "timeout": 1.5}
    assert status == HTTPStatus.OK
    assert error is None


def test_resolve_future_result_timeout() -> None:
    future = _DummyFuture("timeout")
    ok, result, status, error = _ControlRequestHandler._resolve_future_result(
        future,
        timeout=1.0,
    )
    assert not ok
    assert result is None
    assert status == HTTPStatus.GATEWAY_TIMEOUT
    assert error == "runtime timeout"
    assert future.cancelled


def test_resolve_future_result_runtime_error() -> None:
    ok, result, status, error = _ControlRequestHandler._resolve_future_result(
        _DummyFuture("error"),
        timeout=1.0,
    )
    assert not ok
    assert result is None
    assert status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert error == "runtime error"

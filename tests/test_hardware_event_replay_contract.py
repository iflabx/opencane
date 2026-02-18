import asyncio
import json
import socket
import threading
import time
from urllib import request
from urllib.error import HTTPError

from nanobot.api.hardware_server import HardwareControlServer
from nanobot.hardware.adapter.mock_adapter import MockAdapter
from nanobot.hardware.runtime import DeviceRuntimeCore


class _FakeAgentLoop:
    async def process_direct(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return "replay contract ok"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_loop_thread() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return loop, thread


def _stop_loop_thread(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    if not loop.is_closed():
        loop.close()


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=5) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return int(e.code), json.loads(e.read().decode("utf-8"))


def _get_json(url: str) -> tuple[int, dict]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=5) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return int(e.code), json.loads(e.read().decode("utf-8"))


def _wait_until(
    fetch_fn,  # type: ignore[no-untyped-def]
    predicate,  # type: ignore[no-untyped-def]
    *,
    timeout_s: float = 3.0,
    interval_s: float = 0.05,
):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        value = fetch_fn()
        last = value
        if predicate(value):
            return value
        time.sleep(interval_s)
    raise AssertionError(f"condition not met in {timeout_s}s; last={last}")


def test_control_api_event_replay_nominal_voice_turn_contract() -> None:
    loop, thread = _start_loop_thread()
    runtime = DeviceRuntimeCore(adapter=MockAdapter(), agent_loop=_FakeAgentLoop())
    port = _free_port()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,
        vision=None,
        lifelog=None,
        adapter=runtime.adapter,
        loop=loop,
        auth_enabled=False,
        auth_token="",
        control_api_rate_limit_enabled=False,
    )
    asyncio.run_coroutine_threadsafe(runtime.start(), loop).result(timeout=5)
    server.start()
    time.sleep(0.1)
    try:
        base = f"http://127.0.0.1:{port}"
        device_id = "contract-dev-voice"
        session_id = "contract-sess-voice"
        events = [
            {"device_id": device_id, "session_id": session_id, "seq": 1, "type": "hello", "payload": {}},
            {"device_id": device_id, "session_id": session_id, "seq": 2, "type": "listen_start", "payload": {}},
            {
                "device_id": device_id,
                "session_id": session_id,
                "seq": 3,
                "type": "audio_chunk",
                "payload": {"text": "前方是否安全", "chunk_index": 1},
            },
            {"device_id": device_id, "session_id": session_id, "seq": 4, "type": "listen_stop", "payload": {}},
        ]
        for event in events:
            status, data = _post_json(f"{base}/v1/device/event", event)
            assert status == 200
            assert data.get("success") is True

        def _fetch():  # type: ignore[no-untyped-def]
            return _get_json(f"{base}/v1/runtime/status")

        status_data = _wait_until(
            _fetch,
            lambda item: item[0] == 200
            and int((item[1].get("metrics") or {}).get("voice_turn_total", 0)) >= 1,
            timeout_s=4.0,
        )
        status, data = status_data
        assert status == 200
        metrics = data.get("metrics", {})
        assert int(metrics.get("voice_turn_total", 0)) >= 1
        assert int(metrics.get("events_total", 0)) >= 4
    finally:
        server.stop()
        asyncio.run_coroutine_threadsafe(runtime.stop(), loop).result(timeout=5)
        _stop_loop_thread(loop, thread)


def test_control_api_event_replay_duplicate_and_out_of_order_contract() -> None:
    loop, thread = _start_loop_thread()
    runtime = DeviceRuntimeCore(adapter=MockAdapter(), agent_loop=_FakeAgentLoop())
    port = _free_port()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,
        vision=None,
        lifelog=None,
        adapter=runtime.adapter,
        loop=loop,
        auth_enabled=False,
        auth_token="",
        control_api_rate_limit_enabled=False,
    )
    asyncio.run_coroutine_threadsafe(runtime.start(), loop).result(timeout=5)
    server.start()
    time.sleep(0.1)
    try:
        base = f"http://127.0.0.1:{port}"
        device_id = "contract-dev-dup"
        session_id = "contract-sess-dup"
        events = [
            {"device_id": device_id, "session_id": session_id, "seq": 1, "type": "hello", "payload": {}},
            {"device_id": device_id, "session_id": session_id, "seq": 3, "type": "heartbeat", "payload": {}},
            {"device_id": device_id, "session_id": session_id, "seq": 2, "type": "heartbeat", "payload": {}},
            {"device_id": device_id, "session_id": session_id, "seq": 3, "type": "heartbeat", "payload": {}},
        ]
        for event in events:
            status, data = _post_json(f"{base}/v1/device/event", event)
            assert status == 200
            assert data.get("success") is True

        def _fetch():  # type: ignore[no-untyped-def]
            return _get_json(f"{base}/v1/runtime/status")

        status_data = _wait_until(
            _fetch,
            lambda item: item[0] == 200
            and int((item[1].get("metrics") or {}).get("duplicate_events_total", 0)) >= 1,
            timeout_s=4.0,
        )
        status, data = status_data
        assert status == 200
        metrics = data.get("metrics", {})
        assert int(metrics.get("duplicate_events_total", 0)) >= 1
        devices = data.get("devices", [])
        device_state = next(
            (
                item
                for item in devices
                if isinstance(item, dict)
                and str(item.get("device_id") or "") == device_id
                and str(item.get("session_id") or "") == session_id
            ),
            {},
        )
        assert int(device_state.get("last_seq", 0)) == 3
    finally:
        server.stop()
        asyncio.run_coroutine_threadsafe(runtime.stop(), loop).result(timeout=5)
        _stop_loop_thread(loop, thread)

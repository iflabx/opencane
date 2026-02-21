import asyncio
import json
import socket
import threading
import time
from urllib import request
from urllib.error import HTTPError

from opencane.api.hardware_server import HardwareControlServer


class _FakeRuntime:
    def __init__(self) -> None:
        self.dispatch_calls: list[dict] = []

    def get_runtime_status(self):  # type: ignore[no-untyped-def]
        return {"running": True}

    def get_device_status(self, device_id: str):  # type: ignore[no-untyped-def]
        if device_id == "missing":
            return None
        return {"device_id": device_id, "state": "ready", "session_id": f"{device_id}-sess"}

    async def abort(self, device_id: str, reason: str = "manual_abort") -> bool:
        del device_id, reason
        return True

    async def dispatch_device_operation(
        self,
        *,
        device_id: str,
        op_type: str,
        payload: dict,
        session_id: str = "",
        trace_id: str = "device-op",
    ):  # type: ignore[no-untyped-def]
        call = {
            "device_id": device_id,
            "op_type": op_type,
            "payload": dict(payload),
            "session_id": session_id,
            "trace_id": trace_id,
        }
        self.dispatch_calls.append(call)
        if device_id == "missing":
            return {"success": False, "error": "device session not found", "error_code": "not_found"}
        return {
            "success": True,
            "device_id": device_id,
            "session_id": session_id or f"{device_id}-sess",
            "op_type": op_type,
            "command_type": op_type,
            "seq": 11,
        }


class _FakeAdapter:
    async def inject_event(self, event):  # type: ignore[no-untyped-def]
        return event


class _FakeLifelogService:
    def __init__(self) -> None:
        self._next = 0
        self.operations: dict[str, dict] = {}

    async def device_operation_enqueue(self, payload):  # type: ignore[no-untyped-def]
        device_id = str(payload.get("device_id") or "").strip()
        op_type = str(payload.get("op_type") or "").strip()
        body = payload.get("payload")
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        if not op_type:
            return {"success": False, "error": "op_type is required"}
        if not isinstance(body, dict):
            return {"success": False, "error": "payload must be object"}
        operation_id = str(payload.get("operation_id") or "").strip()
        if not operation_id:
            self._next += 1
            operation_id = f"op-{self._next}"
        item = {
            "operation_id": operation_id,
            "device_id": device_id,
            "session_id": str(payload.get("session_id") or ""),
            "op_type": op_type,
            "command_type": op_type,
            "status": "queued",
            "payload": dict(body),
            "result": {},
            "error": "",
        }
        self.operations[operation_id] = item
        return {"success": True, "operation": dict(item)}

    async def device_operation_mark(self, payload):  # type: ignore[no-untyped-def]
        operation_id = str(payload.get("operation_id") or "").strip()
        item = self.operations.get(operation_id)
        if not item:
            return {"success": False, "error": "operation not found"}
        item["status"] = str(payload.get("status") or item["status"])
        result = payload.get("result")
        if isinstance(result, dict):
            item["result"] = dict(result)
        item["error"] = str(payload.get("error") or item.get("error") or "")
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            item["session_id"] = session_id
        return {"success": True, "operation": dict(item)}

    async def device_operation_query(self, payload):  # type: ignore[no-untyped-def]
        operation_id = str(payload.get("operation_id") or "").strip()
        if operation_id:
            item = self.operations.get(operation_id)
            return {"success": True, "count": 1 if item else 0, "items": [dict(item)] if item else []}
        device_id = str(payload.get("device_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        items = list(self.operations.values())
        if device_id:
            items = [item for item in items if str(item.get("device_id")) == device_id]
        if status:
            items = [item for item in items if str(item.get("status")) == status]
        return {"success": True, "count": len(items), "items": [dict(item) for item in items]}


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


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=5) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return int(e.code), json.loads(e.read().decode("utf-8"))


def _get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    req = request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=5) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return int(e.code), json.loads(e.read().decode("utf-8"))


def test_control_api_device_ops_endpoints_integration() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    lifelog = _FakeLifelogService()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=lifelog,  # type: ignore[arg-type]
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)
    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/dispatch",
            {
                "device_id": "dev-1",
                "op_type": "set_config",
                "payload": {"volume": 3},
                "trace_id": "trace-op-1",
            },
        )
        assert status == 200
        assert data.get("success") is True
        op = data.get("operation") or {}
        operation_id = str(op.get("operation_id") or "")
        assert operation_id
        assert op.get("status") == "sent"
        assert runtime.dispatch_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/device/ops?device_id=dev-1&status=sent&limit=10&offset=0"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/{operation_id}/ack",
            {"status": "acked", "result": {"device_ack": True}},
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("operation", {}).get("status") == "acked"

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/device/ops?operation_id={operation_id}"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("items", [{}])[0].get("status") == "acked"

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/dev-2/ota_plan",
            {"version": "1.0.1", "url": "https://example.com/fw.bin"},
        )
        assert status == 200
        assert data.get("success") is True

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/dispatch",
            {
                "device_id": "missing",
                "op_type": "tool_call",
                "payload": {"name": "ping"},
            },
        )
        assert status == 404
        assert data.get("success") is False
        assert data.get("error_code") == "not_found"
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_device_ops_accepts_legacy_alias_and_flat_payload() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    lifelog = _FakeLifelogService()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=lifelog,  # type: ignore[arg-type]
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)
    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/dispatch",
            {
                "deviceId": "dev-legacy",
                "operationType": "config",
                "operationId": "legacy-op-1",
                "traceId": "trace-legacy-1",
                "payload": {"volume": 5, "mode": "night"},
            },
        )
        assert status == 200
        assert data.get("success") is True
        assert runtime.dispatch_calls
        first_call = runtime.dispatch_calls[-1]
        assert first_call["device_id"] == "dev-legacy"
        assert first_call["op_type"] == "set_config"
        assert first_call["trace_id"] == "trace-legacy-1"
        assert first_call["payload"]["volume"] == 5

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/dispatch",
            {
                "device_id": "dev-flat",
                "op_type": "tool_call",
                "trace_id": "trace-flat-1",
                "name": "camera.scan",
                "arguments": {"detail": "high"},
            },
        )
        assert status == 200
        assert data.get("success") is True
        second_call = runtime.dispatch_calls[-1]
        assert second_call["device_id"] == "dev-flat"
        assert second_call["op_type"] == "tool_call"
        assert second_call["payload"]["name"] == "camera.scan"
        assert second_call["payload"]["arguments"] == {"detail": "high"}
        assert "op_type" not in second_call["payload"]
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_device_ops_ack_missing_operation_returns_bad_request() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    lifelog = _FakeLifelogService()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=lifelog,  # type: ignore[arg-type]
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)
    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/ops/not-found/ack",
            {"status": "acked", "result": {"ok": True}},
        )
        assert status == 400
        assert data.get("success") is False
        assert "operation not found" in str(data.get("error") or "")
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)

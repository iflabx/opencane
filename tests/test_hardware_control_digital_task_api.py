import asyncio
import json
import socket
import threading
import time
from urllib import request
from urllib.error import HTTPError

from opencane.api.hardware_server import HardwareControlServer
from opencane.storage.sqlite_observability import SQLiteObservabilityStore


class _FakeRuntime:
    def __init__(self) -> None:
        self._status = {
            "running": True,
            "metrics": {},
            "lifelog": {
                "enabled": True,
                "vector_index": {"backend_mode": "memory"},
                "ingest_queue": {
                    "depth": 0,
                    "max_size": 10,
                    "rejected_total": 0,
                    "dropped_total": 0,
                },
            },
            "digital_task": {
                "total": 10,
                "success": 6,
                "failed": 2,
                "timeout": 1,
                "canceled": 1,
                "success_rate": 0.6,
            },
            "safety": {
                "enabled": True,
                "applied": 20,
                "downgraded": 5,
            },
            "devices": [
                {"device_id": "dev-1", "state": "ready"},
                {"device_id": "dev-2", "state": "closed"},
            ],
        }

    def get_runtime_status(self):  # type: ignore[no-untyped-def]
        return dict(self._status)

    def get_device_status(self, device_id: str):  # type: ignore[no-untyped-def]
        return {"device_id": device_id, "state": "ready"}

    async def abort(self, device_id: str, reason: str = "manual_abort") -> bool:
        del device_id, reason
        return True


class _NamedRuntime(_FakeRuntime):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._status["runtime_name"] = name


class _FakeAdapter:
    async def inject_event(self, event):  # type: ignore[no-untyped-def]
        return event


class _FakeDigitalTaskService:
    def __init__(self) -> None:
        self.execute_calls: list[dict] = []
        self.cancel_calls: list[dict] = []
        self.tasks: dict[str, dict] = {}
        self.next_id = 0

    async def execute(self, payload):  # type: ignore[no-untyped-def]
        self.execute_calls.append(dict(payload))
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            return {"success": False, "error": "goal is required", "error_code": "bad_request"}
        self.next_id += 1
        task_id = f"task-{self.next_id}"
        task = {
            "task_id": task_id,
            "session_id": payload.get("session_id") or "sess-1",
            "goal": goal,
            "status": "running",
            "steps": [],
            "result": {},
            "error": "",
            "created_at": 1,
            "updated_at": 1,
        }
        self.tasks[task_id] = task
        return {"success": True, "accepted": True, "task": task}

    async def get_task(self, task_id: str):  # type: ignore[no-untyped-def]
        task = self.tasks.get(task_id)
        if not task:
            return {"success": False, "error": "task not found", "error_code": "not_found"}
        return {"success": True, "task": task}

    async def list_tasks(self, payload):  # type: ignore[no-untyped-def]
        session_id = str(payload.get("session_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        items = list(self.tasks.values())
        if session_id:
            items = [it for it in items if str(it.get("session_id")) == session_id]
        if status:
            items = [it for it in items if str(it.get("status")) == status]
        return {"success": True, "count": len(items), "items": items}

    async def stats(self, payload):  # type: ignore[no-untyped-def]
        session_id = str(payload.get("session_id") or "").strip()
        items = list(self.tasks.values())
        if session_id:
            items = [it for it in items if str(it.get("session_id")) == session_id]
        total = len(items)
        success = len([it for it in items if it.get("status") == "success"])
        return {
            "success": True,
            "stats": {
                "total": total,
                "success": success,
                "success_rate": (success / total) if total else 0.0,
            },
        }

    async def cancel(self, task_id: str, reason: str = "manual_cancel"):  # type: ignore[no-untyped-def]
        self.cancel_calls.append({"task_id": task_id, "reason": reason})
        task = self.tasks.get(task_id)
        if not task:
            return {"success": False, "error": "task not found", "error_code": "not_found"}
        task["status"] = "canceled"
        task["error"] = reason
        return {"success": True, "task": task}


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


def test_control_api_digital_task_endpoints_integration() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    digital_task = _FakeDigitalTaskService()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=digital_task,  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "帮我规划去医院路线"},
        )
        assert status == 200
        assert data.get("success") is True
        task_id = data["task"]["task_id"]
        assert digital_task.execute_calls

        status, data = _get_json(f"http://127.0.0.1:{port}/v1/digital-task/{task_id}")
        assert status == 200
        assert data.get("success") is True
        assert data["task"]["task_id"] == task_id

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/digital-task?session_id=sess-1&limit=10&offset=0"
        )
        assert status == 200
        assert data.get("success") is True
        assert int(data.get("count", 0)) >= 1

        status, data = _get_json(f"http://127.0.0.1:{port}/v1/digital-task/stats?session_id=sess-1")
        assert status == 200
        assert data.get("success") is True
        assert "stats" in data

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/{task_id}/cancel",
            {"reason": "user stop"},
        )
        assert status == 200
        assert data.get("success") is True
        assert data["task"]["status"] == "canceled"
        assert digital_task.cancel_calls
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_digital_task_auth_integration() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    token = "secret-token"
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=True,
        auth_token=token,
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "x"},
        )
        assert status == 401
        assert data.get("error") == "unauthorized"

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status == 200
        assert data.get("success") is True
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_runtime_observability_endpoint() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    runtime._status["metrics"] = {
        "voice_turn_total": 10,
        "voice_turn_failed": 2,
        "voice_turn_avg_latency_ms": 820.5,
        "voice_turn_max_latency_ms": 1490.0,
        "stt_avg_latency_ms": 210.2,
        "stt_max_latency_ms": 560.0,
        "agent_avg_latency_ms": 460.3,
        "agent_max_latency_ms": 980.0,
    }
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _get_json(f"http://127.0.0.1:{port}/v1/runtime/observability")
        assert status == 200
        assert data.get("success") is True
        assert data.get("healthy") is False
        assert data.get("alerts")
        metrics = data.get("metrics", {})
        assert float(metrics.get("task_failure_rate", 0.0)) == 0.4
        assert float(metrics.get("safety_downgrade_rate", 0.0)) == 0.25
        assert float(metrics.get("device_offline_rate", 0.0)) == 0.5
        assert float(metrics.get("ingest_queue_utilization", 0.0)) == 0.0
        assert float(metrics.get("voice_turn_failure_rate", 0.0)) == 0.2
        assert float(metrics.get("voice_turn_avg_latency_ms", 0.0)) == 820.5
        assert float(metrics.get("stt_avg_latency_ms", 0.0)) == 210.2
        assert float(metrics.get("agent_avg_latency_ms", 0.0)) == 460.3

        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port}/v1/runtime/observability?"
            "task_failure_rate_max=0.5&safety_downgrade_rate_max=0.3&device_offline_rate_max=0.6"
            "&ingest_queue_utilization_max=0.9"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("healthy") is True
        assert data.get("alerts") == []

        runtime._status["digital_task"]["failed"] = 4
        runtime._status["digital_task"]["timeout"] = 2
        runtime._status["digital_task"]["canceled"] = 1
        runtime._status["safety"]["downgraded"] = 10
        runtime._status["devices"] = [
            {"device_id": "dev-1", "state": "closed"},
            {"device_id": "dev-2", "state": "closed"},
        ]
        runtime._status["lifelog"]["ingest_queue"]["depth"] = 9
        status, data = _get_json(f"http://127.0.0.1:{port}/v1/runtime/observability")
        assert status == 200
        assert data.get("success") is True
        assert data.get("healthy") is False
        assert any(alert.get("metric") == "ingest_queue_utilization" for alert in data.get("alerts", []))

        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port}/v1/runtime/observability/history?"
            "window_seconds=3600&bucket_seconds=1&max_points=120&include_raw=true"
        )
        assert status == 200
        assert data.get("success") is True
        assert int(data.get("summary", {}).get("sample_count", 0)) >= 3
        assert int(data.get("count", 0)) >= 1
        assert data.get("points")
        first_point = data["points"][0]
        assert "task_failure_rate_avg" in first_point
        assert "safety_downgrade_rate_avg" in first_point
        assert "device_offline_rate_avg" in first_point
        assert "voice_turn_failure_rate_avg" in first_point
        assert "voice_turn_avg_latency_ms_avg" in first_point
        assert "stt_avg_latency_ms_avg" in first_point
        assert "agent_avg_latency_ms_avg" in first_point
        trend = data.get("summary", {}).get("trend", {})
        assert float(trend.get("task_failure_rate_delta", 0.0)) >= 0.0
        assert float(trend.get("safety_downgrade_rate_delta", 0.0)) >= 0.0
        assert float(trend.get("device_offline_rate_delta", 0.0)) >= 0.0
        assert isinstance(data.get("raw_samples"), list)
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_runtime_observability_rejected_alert_requires_active_queue() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    runtime._status["digital_task"] = {"total": 0, "failed": 0, "timeout": 0, "canceled": 0}
    runtime._status["safety"] = {"applied": 0, "downgraded": 0}
    runtime._status["devices"] = []
    runtime._status["lifelog"]["ingest_queue"] = {
        "depth": 0,
        "max_size": 10,
        "rejected_total": 7,
        "dropped_total": 0,
    }
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port}/v1/runtime/observability?"
            "task_failure_rate_max=1&safety_downgrade_rate_max=1&device_offline_rate_max=1"
            "&ingest_queue_utilization_max=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("healthy") is True
        assert all(alert.get("metric") != "ingest_queue_rejected_total" for alert in data.get("alerts", []))

        runtime._status["lifelog"]["ingest_queue"]["depth"] = 3
        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port}/v1/runtime/observability?"
            "task_failure_rate_max=1&safety_downgrade_rate_max=1&device_offline_rate_max=1"
            "&ingest_queue_utilization_max=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("healthy") is False
        assert any(alert.get("metric") == "ingest_queue_rejected_total" for alert in data.get("alerts", []))
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_observability_history_persists_without_lifelog(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "observability.db"
    loop, thread = _start_loop_thread()
    port = _free_port()
    runtime = _FakeRuntime()
    store = SQLiteObservabilityStore(db_path)
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=runtime,  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        observability_store=store,
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port}/v1/runtime/observability?"
            "task_failure_rate_max=1&safety_downgrade_rate_max=1&device_offline_rate_max=1"
        )
        assert status == 200
        assert data.get("success") is True
    finally:
        server.stop()
        store.close()
        _stop_loop_thread(loop, thread)

    loop2, thread2 = _start_loop_thread()
    port2 = _free_port()
    store2 = SQLiteObservabilityStore(db_path)
    server2 = HardwareControlServer(
        host="127.0.0.1",
        port=port2,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop2,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        observability_store=store2,
        auth_enabled=False,
        auth_token="",
    )
    server2.start()
    time.sleep(0.1)
    try:
        status, data = _get_json(
            "http://127.0.0.1:"
            f"{port2}/v1/runtime/observability/history?window_seconds=3600&bucket_seconds=60&max_points=60"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("source") == "sqlite_observability"
        assert int(data.get("summary", {}).get("sample_count", 0)) >= 1
    finally:
        server2.stop()
        store2.close()
        _stop_loop_thread(loop2, thread2)


def test_control_api_servers_do_not_share_handler_runtime_state() -> None:
    loop1, thread1 = _start_loop_thread()
    loop2, thread2 = _start_loop_thread()
    port1 = _free_port()
    port2 = _free_port()
    server1 = HardwareControlServer(
        host="127.0.0.1",
        port=port1,
        runtime=_NamedRuntime("runtime-1"),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop1,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
    )
    server2 = HardwareControlServer(
        host="127.0.0.1",
        port=port2,
        runtime=_NamedRuntime("runtime-2"),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop2,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
    )
    server1.start()
    server2.start()
    time.sleep(0.1)
    try:
        status1, data1 = _get_json(f"http://127.0.0.1:{port1}/v1/runtime/status")
        status2, data2 = _get_json(f"http://127.0.0.1:{port2}/v1/runtime/status")
        assert status1 == 200
        assert status2 == 200
        assert data1.get("runtime_name") == "runtime-1"
        assert data2.get("runtime_name") == "runtime-2"
    finally:
        server1.stop()
        server2.stop()
        _stop_loop_thread(loop1, thread1)
        _stop_loop_thread(loop2, thread2)


def test_control_api_rejects_too_large_request_body() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        max_request_body_bytes=128,
        auth_enabled=False,
        auth_token="",
    )
    server.start()
    time.sleep(0.1)
    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {
                "session_id": "sess-big",
                "goal": "x" * 1024,
            },
        )
        assert status == 413
        assert data.get("success") is False
        assert "too large" in str(data.get("error") or "")
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_rate_limit_blocks_excessive_requests() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
        control_api_rate_limit_enabled=True,
        control_api_rate_limit_rpm=1,
        control_api_rate_limit_burst=0,
    )
    server.start()
    time.sleep(0.1)
    try:
        status, data = _get_json(f"http://127.0.0.1:{port}/v1/runtime/status")
        assert status == 200
        assert data.get("running") is True

        status, data = _get_json(f"http://127.0.0.1:{port}/v1/runtime/status")
        assert status == 429
        assert data.get("error") == "rate_limited"
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_replay_protection_blocks_replayed_nonce() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=None,
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        digital_task=_FakeDigitalTaskService(),  # type: ignore[arg-type]
        auth_enabled=False,
        auth_token="",
        control_api_replay_protection_enabled=True,
        control_api_replay_window_seconds=300,
        control_api_rate_limit_enabled=False,
    )
    server.start()
    time.sleep(0.1)
    try:
        now_seconds = int(time.time())
        headers = {
            "X-Request-Nonce": "nonce-1",
            "X-Request-Timestamp": str(now_seconds),
        }
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "x"},
            headers=headers,
        )
        assert status == 200
        assert data.get("success") is True

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "x"},
            headers=headers,
        )
        assert status == 409
        assert data.get("error") == "replayed_nonce"

        stale_headers = {
            "X-Request-Nonce": "nonce-2",
            "X-Request-Timestamp": str(now_seconds - 1000),
        }
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/digital-task/execute",
            {"session_id": "sess-1", "goal": "x"},
            headers=stale_headers,
        )
        assert status == 400
        assert data.get("error") == "stale_timestamp"
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)

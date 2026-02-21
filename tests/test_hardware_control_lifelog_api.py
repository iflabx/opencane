import asyncio
import json
import socket
import threading
import time
from urllib import request
from urllib.error import HTTPError

from opencane.api.hardware_server import HardwareControlServer


class _FakeRuntime:
    def get_runtime_status(self):  # type: ignore[no-untyped-def]
        return {"running": True}

    def get_device_status(self, device_id: str):  # type: ignore[no-untyped-def]
        return {"device_id": device_id, "state": "ready"}

    async def abort(self, device_id: str, reason: str = "manual_abort") -> bool:
        del device_id, reason
        return True


class _FakeAdapter:
    async def inject_event(self, event):  # type: ignore[no-untyped-def]
        return event


class _FakeLifelogService:
    def __init__(self) -> None:
        self.enqueue_calls: list[dict] = []
        self.query_calls: list[dict] = []
        self.timeline_calls: list[dict] = []
        self.safety_calls: list[dict] = []
        self.safety_stats_calls: list[dict] = []
        self.device_sessions_calls: list[dict] = []
        self.device_register_calls: list[dict] = []
        self.device_bind_calls: list[dict] = []
        self.device_activate_calls: list[dict] = []
        self.device_revoke_calls: list[dict] = []
        self.device_binding_calls: list[dict] = []
        self.observability_record_calls: list[dict] = []
        self.observability_list_calls: list[dict] = []
        self.observability_samples: list[dict] = []
        self.thought_trace_append_calls: list[dict] = []
        self.thought_trace_query_calls: list[dict] = []
        self.thought_trace_replay_calls: list[dict] = []
        self.thought_trace_items: list[dict] = []
        self.telemetry_samples_calls: list[dict] = []
        self.retention_cleanup_calls: list[dict] = []

    async def enqueue_image(self, payload):  # type: ignore[no-untyped-def]
        self.enqueue_calls.append(dict(payload))
        if not payload.get("session_id"):
            return {"success": False, "error": "session_id is required"}
        return {"success": True, "image_id": 123, "session_id": payload["session_id"]}

    async def query(self, payload):  # type: ignore[no-untyped-def]
        self.query_calls.append(dict(payload))
        query = str(payload.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "query is required"}
        return {"success": True, "hits": [{"id": "1", "text": query}]}

    async def timeline_query(self, payload):  # type: ignore[no-untyped-def]
        self.timeline_calls.append(dict(payload))
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        return {
            "success": True,
            "session_id": session_id,
            "count": 1,
            "items": [{"event_type": "image_ingested"}],
        }

    async def safety_query(self, payload):  # type: ignore[no-untyped-def]
        self.safety_calls.append(dict(payload))
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        trace_id = str(payload.get("trace_id") or "").strip()
        return {
            "success": True,
            "session_id": session_id,
            "count": 1,
            "items": [
                {
                    "event_type": "safety_policy",
                    "payload": {"trace_id": trace_id or "t1", "downgraded": True, "source": "task_update"},
                }
            ],
        }

    async def safety_stats(self, payload):  # type: ignore[no-untyped-def]
        self.safety_stats_calls.append(dict(payload))
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return {"success": False, "error": "session_id is required"}
        return {
            "success": True,
            "session_id": session_id,
            "summary": {"total": 3, "downgraded": 1, "downgrade_rate": 0.3333},
            "by_source": {"task_update": 2, "agent_reply": 1},
        }

    async def device_sessions_query(self, payload):  # type: ignore[no-untyped-def]
        self.device_sessions_calls.append(dict(payload))
        return {
            "success": True,
            "count": 1,
            "items": [
                {
                    "device_id": str(payload.get("device_id") or "dev-1"),
                    "session_id": "sess-1",
                    "state": str(payload.get("state") or "ready"),
                }
            ],
        }

    async def device_register(self, payload):  # type: ignore[no-untyped-def]
        self.device_register_calls.append(dict(payload))
        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        return {
            "success": True,
            "device": {"device_id": device_id, "device_token": "token-1", "status": "registered"},
        }

    async def device_bind(self, payload):  # type: ignore[no-untyped-def]
        self.device_bind_calls.append(dict(payload))
        return {"success": True, "device": {"device_id": str(payload.get("device_id") or ""), "status": "bound"}}

    async def device_activate(self, payload):  # type: ignore[no-untyped-def]
        self.device_activate_calls.append(dict(payload))
        return {"success": True, "device": {"device_id": str(payload.get("device_id") or ""), "status": "activated"}}

    async def device_revoke(self, payload):  # type: ignore[no-untyped-def]
        self.device_revoke_calls.append(dict(payload))
        return {"success": True, "device": {"device_id": str(payload.get("device_id") or ""), "status": "revoked"}}

    async def device_binding_query(self, payload):  # type: ignore[no-untyped-def]
        self.device_binding_calls.append(dict(payload))
        return {
            "success": True,
            "count": 1,
            "items": [
                {
                    "device_id": str(payload.get("device_id") or "dev-1"),
                    "status": "activated",
                    "user_id": "user-1",
                }
            ],
        }

    async def thought_trace_append(self, payload):  # type: ignore[no-untyped-def]
        self.thought_trace_append_calls.append(dict(payload))
        trace_id = str(payload.get("trace_id") or "").strip()
        stage = str(payload.get("stage") or "").strip()
        if not trace_id:
            return {"success": False, "error": "trace_id is required"}
        if not stage:
            return {"success": False, "error": "stage is required"}
        item = {
            "id": len(self.thought_trace_items) + 1,
            "trace_id": trace_id,
            "session_id": str(payload.get("session_id") or ""),
            "source": str(payload.get("source") or "manual"),
            "stage": stage,
            "payload": payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            "ts": int(payload.get("ts") or (1000 + len(self.thought_trace_items))),
        }
        self.thought_trace_items.append(item)
        return {"success": True, "trace": dict(item)}

    async def thought_trace_query(self, payload):  # type: ignore[no-untyped-def]
        self.thought_trace_query_calls.append(dict(payload))
        trace_id = str(payload.get("trace_id") or "").strip()
        items = list(self.thought_trace_items)
        if trace_id:
            items = [item for item in items if str(item.get("trace_id")) == trace_id]
        return {"success": True, "count": len(items), "items": items}

    async def thought_trace_replay(self, payload):  # type: ignore[no-untyped-def]
        self.thought_trace_replay_calls.append(dict(payload))
        trace_id = str(payload.get("trace_id") or "").strip()
        if not trace_id:
            return {"success": False, "error": "trace_id is required"}
        items = [item for item in self.thought_trace_items if str(item.get("trace_id")) == trace_id]
        return {
            "success": True,
            "trace_id": trace_id,
            "summary": {"count": len(items), "first_ts": items[0]["ts"] if items else 0, "last_ts": items[-1]["ts"] if items else 0},
            "steps": [
                {
                    "step": idx + 1,
                    "ts": int(item.get("ts") or 0),
                    "source": str(item.get("source") or ""),
                    "stage": str(item.get("stage") or ""),
                    "payload": dict(item.get("payload") or {}),
                }
                for idx, item in enumerate(items)
            ],
            "items": items,
        }

    async def telemetry_samples_query(self, payload):  # type: ignore[no-untyped-def]
        self.telemetry_samples_calls.append(dict(payload))
        return {
            "success": True,
            "count": 1,
            "items": [
                {
                    "id": 1,
                    "device_id": str(payload.get("device_id") or "dev-1"),
                    "session_id": str(payload.get("session_id") or "sess-1"),
                    "schema_version": "opencane.telemetry.v1",
                    "sample": {"battery": {"percent": 80}},
                    "raw": {"battery": 80},
                    "trace_id": str(payload.get("trace_id") or "trace-telemetry"),
                    "ts": 1000,
                }
            ],
        }

    async def retention_cleanup(self, payload):  # type: ignore[no-untyped-def]
        self.retention_cleanup_calls.append(dict(payload))
        return {
            "success": True,
            "deleted": {"telemetry_samples": 1, "runtime_events": 0},
            "retention_days": {"telemetry_samples": int(payload.get("telemetry_samples_days") or 7)},
        }

    def record_observability_sample(self, sample):  # type: ignore[no-untyped-def]
        item = dict(sample)
        self.observability_record_calls.append(item)
        self.observability_samples.append(item)
        return len(self.observability_samples)

    def list_observability_samples(
        self,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 5000,
        offset: int = 0,
    ):  # type: ignore[no-untyped-def]
        self.observability_list_calls.append(
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "limit": limit,
                "offset": offset,
            }
        )
        items = list(self.observability_samples)
        if start_ts is not None:
            items = [item for item in items if int(item.get("ts", 0)) >= int(start_ts)]
        if end_ts is not None:
            items = [item for item in items if int(item.get("ts", 0)) <= int(end_ts)]
        items = sorted(items, key=lambda x: int(x.get("ts", 0)), reverse=True)
        off = max(0, int(offset))
        lim = max(1, int(limit))
        return items[off : off + lim]


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


def test_control_api_lifelog_endpoints_integration() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    lifelog = _FakeLifelogService()
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
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
            f"http://127.0.0.1:{port}/v1/lifelog/enqueue_image",
            {"session_id": "sess-1", "image_base64": "aGVsbG8=", "question": "what"},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.enqueue_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/lifelog/query",
            {"session_id": "sess-1", "query": "楼梯"},
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("hits")
        assert lifelog.query_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/lifelog/thought_trace",
            {"trace_id": "trace-1", "session_id": "sess-1", "source": "unit", "stage": "accepted", "payload": {"k": "v"}},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.thought_trace_append_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/thought_trace?trace_id=trace-1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1
        assert lifelog.thought_trace_query_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/thought_trace/replay?trace_id=trace-1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("summary", {}).get("count") == 1
        assert lifelog.thought_trace_replay_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/telemetry_samples?device_id=dev-1&session_id=sess-1&limit=5&offset=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1
        assert lifelog.telemetry_samples_calls
        assert str(lifelog.telemetry_samples_calls[-1].get("offset")) == "1"

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/lifelog/retention/cleanup",
            {"telemetry_samples_days": 3},
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("deleted", {}).get("telemetry_samples") == 1
        assert lifelog.retention_cleanup_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/timeline?session_id=sess-1&limit=5&offset=2"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1
        assert lifelog.timeline_calls
        assert str(lifelog.timeline_calls[-1].get("offset")) == "2"

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/safety?session_id=sess-1&trace_id=trace-1&downgraded=true&limit=5&offset=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1
        assert lifelog.safety_calls
        assert str(lifelog.safety_calls[-1].get("offset")) == "1"

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/safety/stats?session_id=sess-1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("summary", {}).get("total") == 3
        assert lifelog.safety_stats_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/register",
            {"device_id": "dev-1", "device_token": "token-1"},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.device_register_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/bind",
            {"device_id": "dev-1", "user_id": "user-1"},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.device_bind_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/activate",
            {"device_id": "dev-1"},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.device_activate_calls

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/device/revoke",
            {"device_id": "dev-1", "reason": "manual"},
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.device_revoke_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/device/binding?device_id=dev-1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("items", [{}])[0].get("status") == "activated"
        assert lifelog.device_binding_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/lifelog/device_sessions?device_id=dev-1&state=closed&limit=5&offset=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("count") == 1
        assert lifelog.device_sessions_calls
        assert str(lifelog.device_sessions_calls[-1].get("offset")) == "1"

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/runtime/observability?task_failure_rate_max=1&safety_downgrade_rate_max=1&device_offline_rate_max=1"
        )
        assert status == 200
        assert data.get("success") is True
        assert lifelog.observability_record_calls

        status, data = _get_json(
            f"http://127.0.0.1:{port}/v1/runtime/observability/history?window_seconds=3600&bucket_seconds=60&max_points=60"
        )
        assert status == 200
        assert data.get("success") is True
        assert data.get("source") == "sqlite"
        assert int(data.get("summary", {}).get("sample_count", 0)) >= 1
        assert lifelog.observability_list_calls
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)


def test_control_api_lifelog_auth_integration() -> None:
    loop, thread = _start_loop_thread()
    port = _free_port()
    token = "secret-token"
    server = HardwareControlServer(
        host="127.0.0.1",
        port=port,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        vision=None,
        lifelog=_FakeLifelogService(),  # type: ignore[arg-type]
        adapter=_FakeAdapter(),  # type: ignore[arg-type]
        loop=loop,
        auth_enabled=True,
        auth_token=token,
    )
    server.start()
    time.sleep(0.1)

    try:
        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/lifelog/query",
            {"session_id": "sess-1", "query": "x"},
        )
        assert status == 401
        assert data.get("error") == "unauthorized"

        status, data = _post_json(
            f"http://127.0.0.1:{port}/v1/lifelog/query",
            {"session_id": "sess-1", "query": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status == 200
        assert data.get("success") is True
    finally:
        server.stop()
        _stop_loop_thread(loop, thread)

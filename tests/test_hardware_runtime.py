import asyncio
from typing import Any

import pytest

from nanobot.hardware.adapter.mock_adapter import MockAdapter
from nanobot.hardware.protocol import DeviceEventType, make_event
from nanobot.hardware.runtime import DeviceRuntimeCore
from nanobot.hardware.runtime.session_manager import ConnectionState
from nanobot.safety.interaction_policy import InteractionPolicy


class FakeAgentLoop:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def process_direct(self, content: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"content": content, "kwargs": dict(kwargs)})
        return f"agent:{content}"

    async def close_mcp(self) -> None:
        return None


class FakeVisionService:
    async def analyze_payload(self, payload):  # type: ignore[no-untyped-def]
        return {"success": True, "result": "vision:door ahead"}


class FakeLifelogService:
    def __init__(self) -> None:
        self.runtime_events: list[dict] = []
        self.image_requests: list[dict] = []
        self.auth_calls: list[dict] = []

    def record_runtime_event(self, **kwargs):  # type: ignore[no-untyped-def]
        self.runtime_events.append(kwargs)
        return len(self.runtime_events)

    async def enqueue_image(self, payload):  # type: ignore[no-untyped-def]
        self.image_requests.append(dict(payload))
        return {"success": True, "image_id": 1}

    def status_snapshot(self):  # type: ignore[no-untyped-def]
        return {
            "enabled": True,
            "vector_index": {"backend_mode": "memory", "persistent": False},
        }

    def validate_device_auth(
        self,
        *,
        device_id: str,
        device_token: str,
        require_activated: bool = True,
        allow_unbound: bool = False,
    ):  # type: ignore[no-untyped-def]
        self.auth_calls.append(
            {
                "device_id": device_id,
                "device_token": device_token,
                "require_activated": require_activated,
                "allow_unbound": allow_unbound,
            }
        )
        if device_token == "token-ok":
            return {
                "success": True,
                "reason": "ok",
                "binding": {"status": "activated", "user_id": "user-1"},
            }
        return {"success": False, "reason": "invalid_device_token", "binding": None}


class FakeDigitalTaskService:
    def __init__(self) -> None:
        self.execute_calls: list[dict] = []
        self.flush_calls: list[dict] = []

    async def execute(self, payload):  # type: ignore[no-untyped-def]
        self.execute_calls.append(dict(payload))
        return {"success": True, "task": {"task_id": "task-voice-1"}}

    async def flush_pending_updates(self, *, device_id: str, session_id: str = "", limit: int = 20):  # type: ignore[no-untyped-def]
        self.flush_calls.append(
            {"device_id": device_id, "session_id": session_id, "limit": int(limit)}
        )
        return {"success": True, "sent": 0, "retry": 0}


class FakeSafetyPolicy:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def evaluate(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        text = str(kwargs.get("text") or "")
        return {
            "text": f"safe:{text}",
            "risk_level": "P2",
            "confidence": 0.6,
            "downgraded": True,
            "reason": "test_policy",
            "flags": ["test"],
        }


class FakeTTSSynthesizer:
    async def synthesize(self, text: str):  # type: ignore[no-untyped-def]
        if not text.strip():
            return None
        return {
            "audio_b64": "UklGRgAAAAA=",
            "encoding": "wav",
            "sample_rate_hz": 16000,
        }


class FakeControlPlaneClient:
    def __init__(self, policy: dict[str, Any] | None = None) -> None:
        self.policy = policy or {"allow_tools": ["web_search"]}
        self.calls: list[dict[str, Any]] = []

    async def fetch_device_policy(self, *, device_id: str, force_refresh: bool = False):  # type: ignore[no-untyped-def]
        self.calls.append({"device_id": device_id, "force_refresh": bool(force_refresh)})
        return {
            "success": True,
            "source": "remote",
            "data": dict(self.policy),
        }


@pytest.mark.asyncio
async def test_runtime_voice_round_trip() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-voice"
        session_id = "sess-1"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=2,
                payload={"text": "where am i"},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_STOP, device_id=device_id, session_id=session_id, seq=3)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        cmd_types = [cmd.type for cmd in cmds]
        assert "hello_ack" in cmd_types
        assert "stt_final" in cmd_types
        assert "tts_start" in cmd_types
        assert "tts_chunk" in cmd_types
        assert "tts_stop" in cmd_types
        seqs = [cmd.seq for cmd in cmds]
        assert all(seq > 0 for seq in seqs)
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_audio_chunk_reorder_emits_partial_and_final() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-reorder"
        session_id = "sess-reorder"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=4,
                payload={"text": "world", "chunk_index": 2},
            )
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=3,
                payload={"text": "hello", "chunk_index": 1},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_STOP, device_id=device_id, session_id=session_id, seq=5)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        partials = [str(c.payload.get("text", "")) for c in cmds if c.type == "stt_partial"]
        finals = [str(c.payload.get("text", "")) for c in cmds if c.type == "stt_final"]
        assert partials
        assert finals
        assert finals[-1] == "hello world"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_listen_start_interrupts_speaking_state() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-barge-in"
        session_id = "sess-barge-in"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.05)
        runtime.sessions.update_state(device_id, session_id, ConnectionState.SPEAKING)
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        tts_stops = [c for c in cmds if c.type == "tts_stop" and bool(c.payload.get("aborted"))]
        assert tts_stops
        assert any(str(c.payload.get("reason") or "") == "barge_in" for c in tts_stops)
        status = runtime.get_device_status(device_id) or {}
        assert status.get("state") == "listening"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_image_event_triggers_tts() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        vision_service=FakeVisionService(),
    )
    await runtime.start()
    try:
        device_id = "dev-vision"
        session_id = "sess-v"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.IMAGE_READY,
                device_id=device_id,
                session_id=session_id,
                seq=4,
                payload={"image_base64": "aGVsbG8=", "question": "what do you see"},
            )
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        text_payloads = [c.payload.get("text", "") for c in cmds if c.type == "tts_chunk"]
        assert any("vision:door ahead" in p for p in text_payloads)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_server_audio_mode_emits_audio_chunks() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        tts_mode="server_audio",
        tts_synthesizer=FakeTTSSynthesizer(),
    )
    await runtime.start()
    try:
        device_id = "dev-audio"
        session_id = "sess-audio"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=3,
                payload={"text": "where am i"},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_STOP, device_id=device_id, session_id=session_id, seq=4)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        audio_chunks = [c for c in cmds if c.type == "tts_chunk"]
        assert audio_chunks
        assert all(c.payload.get("audio_b64") for c in audio_chunks)
        assert all("text" not in c.payload for c in audio_chunks)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_duplicate_heartbeat_is_acked() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-dup"
        session_id = "sess-dup"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.HEARTBEAT, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.HEARTBEAT, device_id=device_id, session_id=session_id, seq=2)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        ack_cmds = [c for c in cmds if c.type == "ack" and c.payload.get("ack_seq") == 2]
        assert len(ack_cmds) == 2
        assert len({c.seq for c in ack_cmds}) == 2
        assert all(c.seq > 0 for c in ack_cmds)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_out_of_order_heartbeat_is_acked_and_discarded() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-ooo"
        session_id = "sess-ooo"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.HEARTBEAT, device_id=device_id, session_id=session_id, seq=3)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.HEARTBEAT, device_id=device_id, session_id=session_id, seq=2)
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        ack_cmds = [c for c in cmds if c.type == "ack"]
        ack_seqs = [int(c.payload.get("ack_seq", -1)) for c in ack_cmds]
        assert ack_seqs.count(3) == 1
        assert ack_seqs.count(2) == 1
        status = runtime.get_device_status(device_id) or {}
        assert status.get("last_seq") == 3
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_duplicate_hello_reissues_hello_ack() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-hello-dup"
        session_id = "sess-hello-dup"
        hello = make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=5)
        await adapter.inject_event(hello)
        await adapter.inject_event(hello)
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        hello_acks = [c for c in cmds if c.type == "hello_ack"]
        assert len(hello_acks) == 2
        assert all(int(c.payload.get("ack_seq", -1)) == 5 for c in hello_acks)
        assert len({c.seq for c in hello_acks}) == 2
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_status_exposes_metrics() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-metric"
        session_id = "sess-metric"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.HEARTBEAT, device_id=device_id, session_id=session_id, seq=2)
        )
        await asyncio.sleep(0.2)
        status = runtime.get_runtime_status()
        metrics = status.get("metrics", {})
        assert int(metrics.get("events_total", 0)) >= 2
        assert int(metrics.get("commands_total", 0)) >= 2
        assert int(metrics.get("events_by_type", {}).get("hello", 0)) >= 1
        assert int(metrics.get("commands_by_type", {}).get("hello_ack", 0)) >= 1
        assert status.get("running") is True
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_status_exposes_lifelog_vector_backend() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        lifelog_service=FakeLifelogService(),
    )
    await runtime.start()
    try:
        status = runtime.get_runtime_status()
        lifelog = status.get("lifelog", {})
        vector = lifelog.get("vector_index", {}) if isinstance(lifelog, dict) else {}
        assert lifelog.get("enabled") is True
        assert vector.get("backend_mode") == "memory"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_voice_turn_is_written_to_lifelog() -> None:
    adapter = MockAdapter()
    lifelog = FakeLifelogService()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop(), lifelog_service=lifelog)
    await runtime.start()
    try:
        device_id = "dev-voice-log"
        session_id = "sess-voice-log"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=3,
                payload={"text": "where am i"},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_STOP, device_id=device_id, session_id=session_id, seq=4)
        )
        await asyncio.sleep(0.2)
        assert any(e.get("event_type") == "voice_turn" for e in lifelog.runtime_events)
        metrics = runtime.get_runtime_status().get("metrics", {})
        assert int(metrics.get("voice_turn_total", 0)) >= 1
        assert int(metrics.get("voice_turn_failed", 0)) == 0
        assert float(metrics.get("voice_turn_avg_latency_ms", 0.0)) >= 0.0
        assert float(metrics.get("stt_avg_latency_ms", 0.0)) >= 0.0
        assert float(metrics.get("agent_avg_latency_ms", 0.0)) >= 0.0
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_image_ready_triggers_lifelog_ingest() -> None:
    adapter = MockAdapter()
    lifelog = FakeLifelogService()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        vision_service=FakeVisionService(),
        lifelog_service=lifelog,
    )
    await runtime.start()
    try:
        device_id = "dev-image-log"
        session_id = "sess-image-log"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.IMAGE_READY,
                device_id=device_id,
                session_id=session_id,
                seq=2,
                payload={"image_base64": "aGVsbG8=", "question": "what do you see"},
            )
        )
        await asyncio.sleep(0.2)
        assert len(lifelog.image_requests) == 1
        assert lifelog.image_requests[0]["session_id"] == session_id
        assert any(e.get("event_type") == "image_turn" for e in lifelog.runtime_events)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_push_task_update_sends_task_and_tts_commands() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-task-push"
        session_id = "sess-task-push"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.1)
        pushed = await runtime.push_task_update(
            task_id="task-1",
            status="running",
            message="任务处理中，请稍候。",
            device_id=device_id,
            session_id=session_id,
            speak=True,
            extra={"event": "running"},
        )
        assert pushed is True
        cmds = adapter.pending_commands()
        cmd_types = [cmd.type for cmd in cmds]
        assert "task_update" in cmd_types
        assert "tts_start" in cmd_types
        assert "tts_chunk" in cmd_types
        assert "tts_stop" in cmd_types

        pushed_missing = await runtime.push_task_update(
            task_id="task-2",
            status="running",
            message="x",
            device_id="unknown-device",
            session_id="",
            speak=False,
        )
        assert pushed_missing is False
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_push_task_update_can_be_silenced_by_interaction_policy() -> None:
    adapter = MockAdapter()
    interaction = InteractionPolicy(
        enabled=True,
        emotion_enabled=False,
        proactive_enabled=False,
        silent_enabled=True,
        silent_sources=["task_update"],
        quiet_hours_enabled=True,
        quiet_hours_start_hour=23,
        quiet_hours_end_hour=7,
        suppress_low_priority_in_quiet_hours=True,
        current_hour_fn=lambda: 23,
    )
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        interaction_policy=interaction,
    )
    await runtime.start()
    try:
        device_id = "dev-task-silent"
        session_id = "sess-task-silent"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.1)
        pushed = await runtime.push_task_update(
            task_id="task-1",
            status="running",
            message="任务处理中，请稍候。",
            device_id=device_id,
            session_id=session_id,
            speak=True,
            extra={"event": "running", "priority": "low"},
        )
        assert pushed is True
        cmds = adapter.pending_commands()
        task_updates = [cmd for cmd in cmds if cmd.type == "task_update"]
        tts_chunks = [cmd for cmd in cmds if cmd.type == "tts_chunk"]
        tts_stops = [cmd for cmd in cmds if cmd.type == "tts_stop"]
        assert task_updates
        assert not tts_chunks
        assert any(str(cmd.payload.get("reason") or "") == "interaction_policy_silent" for cmd in tts_stops)

        status = runtime.get_runtime_status().get("interaction", {})
        assert status.get("enabled") is True
        assert int(status.get("suppressed", 0)) >= 1
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_image_event_applies_interaction_proactive_hint() -> None:
    adapter = MockAdapter()
    interaction = InteractionPolicy(
        enabled=True,
        emotion_enabled=False,
        proactive_enabled=True,
        silent_enabled=False,
        proactive_sources=["vision_reply"],
    )
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        vision_service=FakeVisionService(),
        interaction_policy=interaction,
    )
    await runtime.start()
    try:
        device_id = "dev-vision-proactive"
        session_id = "sess-vision-proactive"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.IMAGE_READY,
                device_id=device_id,
                session_id=session_id,
                seq=2,
                payload={"image_base64": "aGVsbG8=", "question": "what do you see"},
            )
        )
        await asyncio.sleep(0.2)
        chunks = [str(c.payload.get("text", "")) for c in adapter.pending_commands() if c.type == "tts_chunk"]
        assert any("vision:door ahead" in text for text in chunks)
        assert any("可通行方向" in text for text in chunks)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_dispatch_device_operation_sends_mapped_command() -> None:
    adapter = MockAdapter()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop())
    await runtime.start()
    try:
        device_id = "dev-op-dispatch"
        session_id = "sess-op-dispatch"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.1)
        result = await runtime.dispatch_device_operation(
            device_id=device_id,
            session_id=session_id,
            op_type="ota_plan",
            payload={"version": "1.2.3"},
            trace_id="op-trace-1",
        )
        assert result["success"] is True
        assert result["command_type"] == "ota_plan"
        cmds = adapter.pending_commands()
        ota = [cmd for cmd in cmds if cmd.type == "ota_plan"]
        assert ota
        assert ota[-1].payload.get("version") == "1.2.3"

        missing = await runtime.dispatch_device_operation(
            device_id="unknown",
            op_type="set_config",
            payload={"key": "v"},
        )
        assert missing["success"] is False
        assert missing["error_code"] == "not_found"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_voice_turn_applies_device_policy_and_runtime_context() -> None:
    adapter = MockAdapter()
    agent = FakeAgentLoop()
    control_plane = FakeControlPlaneClient(
        policy={"allow_tools": ["web_search", "web_fetch"], "blocked_tools": ["web_fetch"]}
    )
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=agent,
        control_plane_client=control_plane,
    )
    await runtime.start()
    try:
        device_id = "dev-policy"
        session_id = "sess-policy"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.TELEMETRY,
                device_id=device_id,
                session_id=session_id,
                seq=2,
                payload={"battery": 88},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=3)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=4,
                payload={"text": "search nearby crossing"},
            )
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.LISTEN_STOP,
                device_id=device_id,
                session_id=session_id,
                seq=5,
                payload={"trace_id": "trace-policy-1"},
            )
        )
        await asyncio.sleep(0.2)

        assert control_plane.calls
        assert control_plane.calls[-1]["device_id"] == device_id
        assert agent.calls
        kwargs = dict(agent.calls[-1]["kwargs"])
        assert kwargs.get("allowed_tool_names") == {"web_search"}
        assert kwargs.get("blocked_tool_names") == {"web_fetch"}
        metadata = kwargs.get("message_metadata")
        meta = metadata if isinstance(metadata, dict) else {}
        runtime_context = meta.get("runtime_context")
        context = runtime_context if isinstance(runtime_context, dict) else {}
        assert context.get("device_id") == device_id
        assert context.get("session_id") == session_id
        assert context.get("trace_id") == "trace-policy-1"
        assert context.get("telemetry", {}).get("battery") == 88
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_voice_turn_supports_deny_only_device_policy() -> None:
    adapter = MockAdapter()
    agent = FakeAgentLoop()
    control_plane = FakeControlPlaneClient(
        policy={"blocked_tools": ["exec", "write_file"]}
    )
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=agent,
        control_plane_client=control_plane,
    )
    await runtime.start()
    try:
        device_id = "dev-policy-deny"
        session_id = "sess-policy-deny"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=3,
                payload={"text": "what can you do"},
            )
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.LISTEN_STOP,
                device_id=device_id,
                session_id=session_id,
                seq=4,
            )
        )
        await asyncio.sleep(0.2)
        assert agent.calls
        kwargs = dict(agent.calls[-1]["kwargs"])
        assert kwargs.get("allowed_tool_names") is None
        assert kwargs.get("blocked_tool_names") == {"exec", "write_file"}
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_push_task_update_sanitizes_payload_message_once() -> None:
    adapter = MockAdapter()
    safety = FakeSafetyPolicy()
    lifelog = FakeLifelogService()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        lifelog_service=lifelog,
        safety_policy=safety,
    )
    await runtime.start()
    try:
        device_id = "dev-task-safe"
        session_id = "sess-task-safe"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.1)
        pushed = await runtime.push_task_update(
            task_id="task-safe-1",
            status="running",
            message="请继续向前并右转",
            device_id=device_id,
            session_id=session_id,
            speak=True,
            extra={"event": "running"},
        )
        assert pushed is True
        cmds = adapter.pending_commands()
        task_updates = [cmd for cmd in cmds if cmd.type == "task_update"]
        assert task_updates
        assert str(task_updates[-1].payload.get("message", "")).startswith("safe:")
        tts_chunks = [str(cmd.payload.get("text", "")) for cmd in cmds if cmd.type == "tts_chunk"]
        assert any(chunk.startswith("safe:") for chunk in tts_chunks)
        assert len(safety.calls) == 1
        assert any(e.get("event_type") == "safety_policy" for e in lifelog.runtime_events)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_push_task_update_applies_safety_policy_and_audit() -> None:
    adapter = MockAdapter()
    lifelog = FakeLifelogService()
    safety = FakeSafetyPolicy()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        lifelog_service=lifelog,
        safety_policy=safety,
    )
    await runtime.start()
    try:
        device_id = "dev-task-safe"
        session_id = "sess-task-safe"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.1)
        pushed = await runtime.push_task_update(
            task_id="task-safe-1",
            status="running",
            message="请继续直行。",
            device_id=device_id,
            session_id=session_id,
            speak=True,
            extra={"event": "running", "confidence": 0.2},
        )
        assert pushed is True
        await asyncio.sleep(0.05)
        cmds = adapter.pending_commands()
        text_payloads = [c.payload.get("text", "") for c in cmds if c.type == "tts_chunk"]
        assert any("safe:请继续直行。" in p for p in text_payloads)
        assert len(safety.calls) >= 1
        assert any(e.get("event_type") == "safety_policy" for e in lifelog.runtime_events)

        runtime_status = runtime.get_runtime_status()
        safety_status = runtime_status.get("safety", {})
        assert safety_status.get("enabled") is True
        assert int(safety_status.get("applied", 0)) >= 1
        assert int(safety_status.get("downgraded", 0)) >= 1
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_voice_intent_routes_to_digital_task() -> None:
    adapter = MockAdapter()
    agent = FakeAgentLoop()
    digital = FakeDigitalTaskService()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=agent, digital_task_service=digital)
    await runtime.start()
    try:
        device_id = "dev-task-route"
        session_id = "sess-task-route"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_START, device_id=device_id, session_id=session_id, seq=2)
        )
        await adapter.inject_event(
            make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id,
                seq=3,
                payload={"text": "帮我挂号"},
            )
        )
        await adapter.inject_event(
            make_event(DeviceEventType.LISTEN_STOP, device_id=device_id, session_id=session_id, seq=4)
        )
        await asyncio.sleep(0.2)
        assert len(digital.execute_calls) == 1
        assert digital.execute_calls[0]["device_id"] == device_id
        assert digital.execute_calls[0]["session_id"] == session_id
        assert len(agent.calls) == 0
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_hello_triggers_digital_push_flush() -> None:
    adapter = MockAdapter()
    digital = FakeDigitalTaskService()
    runtime = DeviceRuntimeCore(adapter=adapter, agent_loop=FakeAgentLoop(), digital_task_service=digital)
    await runtime.start()
    try:
        device_id = "dev-task-flush"
        session_id = "sess-task-flush"
        await adapter.inject_event(
            make_event(DeviceEventType.HELLO, device_id=device_id, session_id=session_id, seq=1)
        )
        await asyncio.sleep(0.2)
        assert len(digital.flush_calls) == 1
        call = digital.flush_calls[0]
        assert call["device_id"] == device_id
        assert call["session_id"] == session_id
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_device_auth_denied_closes_session() -> None:
    adapter = MockAdapter()
    lifelog = FakeLifelogService()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        lifelog_service=lifelog,
        device_auth_enabled=True,
        require_activated_devices=True,
    )
    await runtime.start()
    try:
        await adapter.inject_event(
            make_event(
                DeviceEventType.HELLO,
                device_id="dev-auth-deny",
                session_id="sess-auth-deny",
                seq=1,
                payload={"device_token": "wrong-token"},
            )
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        cmd_types = [cmd.type for cmd in cmds]
        assert "close" in cmd_types
        assert "hello_ack" not in cmd_types
        devices = runtime.get_runtime_status().get("devices", [])
        denied = [
            item for item in devices
            if isinstance(item, dict) and item.get("device_id") == "dev-auth-deny"
        ]
        assert denied
        assert denied[0].get("state") == "closed"
        assert lifelog.auth_calls
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_device_auth_passes_with_valid_token() -> None:
    adapter = MockAdapter()
    lifelog = FakeLifelogService()
    runtime = DeviceRuntimeCore(
        adapter=adapter,
        agent_loop=FakeAgentLoop(),
        lifelog_service=lifelog,
        device_auth_enabled=True,
        require_activated_devices=True,
    )
    await runtime.start()
    try:
        await adapter.inject_event(
            make_event(
                DeviceEventType.HELLO,
                device_id="dev-auth-ok",
                session_id="sess-auth-ok",
                seq=1,
                payload={"device_token": "token-ok"},
            )
        )
        await asyncio.sleep(0.2)
        cmds = adapter.pending_commands()
        cmd_types = [cmd.type for cmd in cmds]
        assert "hello_ack" in cmd_types
        status = runtime.get_device_status("dev-auth-ok") or {}
        assert status.get("state") == "ready"
        assert status.get("metadata", {}).get("auth_passed") is True
    finally:
        await runtime.stop()

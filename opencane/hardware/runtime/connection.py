"""Device runtime core orchestrating adapter events and agent responses."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from collections.abc import Iterable
from typing import Any

from loguru import logger

from opencane.hardware.adapter.base import GatewayAdapter
from opencane.hardware.observability import HardwareRuntimeMetrics
from opencane.hardware.protocol import (
    CanonicalEnvelope,
    DeviceCommandType,
    DeviceEventType,
    make_command,
)
from opencane.hardware.runtime.audio_pipeline import AudioPipeline
from opencane.hardware.runtime.session_manager import (
    ConnectionState,
    DeviceSession,
    DeviceSessionManager,
)
from opencane.hardware.runtime.telemetry import normalize_telemetry_payload


class DeviceRuntimeCore:
    """Canonical runtime for hardware events independent of southbound protocol."""

    def __init__(
        self,
        *,
        adapter: GatewayAdapter,
        agent_loop: Any,
        session_manager: DeviceSessionManager | None = None,
        audio_pipeline: AudioPipeline | None = None,
        vision_service: Any | None = None,
        lifelog_service: Any | None = None,
        digital_task_service: Any | None = None,
        safety_policy: Any | None = None,
        interaction_policy: Any | None = None,
        tts_mode: str = "device_text",
        tts_synthesizer: Any | None = None,
        tts_audio_chunk_bytes: int = 1600,
        no_heartbeat_timeout_s: int = 60,
        device_auth_enabled: bool = False,
        allow_unbound_devices: bool = False,
        require_activated_devices: bool = True,
        control_plane_client: Any | None = None,
        tool_result_enabled: bool = False,
        tool_result_mark_device_operation_enabled: bool = True,
        telemetry_normalize_enabled: bool = False,
        telemetry_persist_samples_enabled: bool = False,
    ) -> None:
        self.adapter = adapter
        self.agent_loop = agent_loop
        self.lifelog = lifelog_service
        if session_manager is None:
            persistence_store = self._resolve_session_persistence_store(lifelog_service)
            self.sessions = DeviceSessionManager(persistence_store=persistence_store)
        else:
            self.sessions = session_manager
        self.audio = audio_pipeline or AudioPipeline()
        self.vision_service = vision_service
        self.digital_task = digital_task_service
        self.safety_policy = safety_policy
        self.interaction_policy = interaction_policy
        self.tts_mode = str(tts_mode or "device_text").strip().lower()
        self.tts_synthesizer = tts_synthesizer
        self.tts_audio_chunk_bytes = max(256, int(tts_audio_chunk_bytes))
        self.no_heartbeat_timeout_s = max(10, no_heartbeat_timeout_s)
        self.device_auth_enabled = bool(device_auth_enabled)
        self.allow_unbound_devices = bool(allow_unbound_devices)
        self.require_activated_devices = bool(require_activated_devices)
        self.control_plane_client = control_plane_client
        self.tool_result_enabled = bool(tool_result_enabled)
        self.tool_result_mark_device_operation_enabled = bool(tool_result_mark_device_operation_enabled)
        self.telemetry_normalize_enabled = bool(telemetry_normalize_enabled)
        self.telemetry_persist_samples_enabled = bool(telemetry_persist_samples_enabled)
        self.metrics = HardwareRuntimeMetrics()
        self._running = False
        self._event_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._inflight_tasks: set[asyncio.Task] = set()
        self._safety_applied = 0
        self._safety_downgraded = 0
        self._interaction_applied = 0
        self._interaction_suppressed = 0
        self._stt_partial_state: dict[tuple[str, str], tuple[str, int]] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.adapter.start()
        self._event_task = asyncio.create_task(self._event_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("Device runtime core started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for state in self.sessions.all_status():
            if str(state.get("state") or "").strip().lower() == ConnectionState.CLOSED.value:
                continue
            device_id = str(state.get("device_id") or "").strip()
            session_id = str(state.get("session_id") or "").strip()
            if not device_id or not session_id:
                continue
            self.sessions.close(device_id, session_id, reason="runtime_stop")
        await self.adapter.stop()
        for task in [self._event_task, self._watchdog_task]:
            if task:
                task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            if self._event_task:
                await self._event_task
        with contextlib.suppress(asyncio.CancelledError):
            if self._watchdog_task:
                await self._watchdog_task
        for task in list(self._inflight_tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._inflight_tasks.clear()
        self._stt_partial_state.clear()
        logger.info("Device runtime core stopped")

    async def _event_loop(self) -> None:
        async for event in self.adapter.recv_events():
            try:
                await self.handle_event(event)
            except Exception as e:
                logger.error(f"Device runtime handle_event failed: {e}")

    async def _watchdog_loop(self) -> None:
        while self._running:
            await asyncio.sleep(2.0)
            now_ms = int(time.time() * 1000)
            timeout_ms = self.no_heartbeat_timeout_s * 1000
            for state in self.sessions.all_status():
                last_seen = int(state.get("last_seen_ms", 0))
                if state.get("state") == ConnectionState.CLOSED.value:
                    continue
                if last_seen and now_ms - last_seen > timeout_ms:
                    device_id = state["device_id"]
                    session_id = state["session_id"]
                    logger.info(f"Closing stale session {device_id}/{session_id}")
                    self.sessions.close(device_id, session_id, reason="heartbeat_timeout")
                    await self.adapter.close_session(device_id, session_id, "heartbeat_timeout")

    async def handle_event(self, event: CanonicalEnvelope) -> None:
        trace_id = self._trace_id_for_event(event)
        self.metrics.record_event(event.type)
        logger.debug(
            f"hw-event type={event.type} trace_id={trace_id} "
            f"device_id={event.device_id} session_id={event.session_id} seq={event.seq}"
        )
        session = self.sessions.get_or_create(event.device_id, event.session_id)
        if not await self._ensure_device_authorized(session, event, trace_id=trace_id):
            return
        seq_committed = True
        if event.seq >= 0:
            seq_committed = self.sessions.check_and_commit_seq(
                event.device_id,
                event.session_id,
                event.seq,
            )
        if not seq_committed and event.type != DeviceEventType.AUDIO_CHUNK:
            self.metrics.record_duplicate_event(event.type)
            if event.type == DeviceEventType.HELLO:
                await self._on_hello(session, event, trace_id=trace_id)
            elif event.type in {
                DeviceEventType.HEARTBEAT,
                DeviceEventType.LISTEN_START,
                DeviceEventType.LISTEN_STOP,
                DeviceEventType.TELEMETRY,
                DeviceEventType.TOOL_RESULT,
            }:
                await self._send_ack(session, event.seq, trace_id=trace_id)
            logger.debug(f"Discard duplicate event seq={event.seq} {event.device_id}/{event.session_id}")
            return

        if event.type == DeviceEventType.HELLO:
            await self._on_hello(session, event, trace_id=trace_id)
            await self._record_lifelog_event(
                session,
                "hello",
                payload={"trace_id": trace_id, "capabilities": event.payload.get("capabilities", {})},
            )
        elif event.type == DeviceEventType.HEARTBEAT:
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
            await self._send_ack(session, event.seq, trace_id=trace_id)
        elif event.type == DeviceEventType.LISTEN_START:
            if session.state == ConnectionState.SPEAKING:
                await self._send_tts_stop(
                    session,
                    aborted=True,
                    reason="barge_in",
                    trace_id=trace_id,
                )
                await self._record_lifelog_event(
                    session,
                    "voice_interrupt",
                    payload={"trace_id": trace_id, "reason": "barge_in"},
                    confidence=1.0,
                )
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.LISTENING)
            self.audio.start_capture(session)
            self._clear_partial_state(session)
            await self._send_ack(session, event.seq, trace_id=trace_id)
            await self._record_lifelog_event(
                session,
                "listen_start",
                payload={"trace_id": trace_id, "seq": event.seq},
            )
        elif event.type == DeviceEventType.AUDIO_CHUNK:
            partial = await self.audio.append_chunk(
                session,
                event.payload,
                event_seq=event.seq,
            )
            await self._maybe_emit_stt_partial(session, partial, trace_id=trace_id)
        elif event.type == DeviceEventType.LISTEN_STOP:
            self._clear_partial_state(session)
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.THINKING)
            await self._send_ack(session, event.seq, trace_id=trace_id)
            self._spawn(self._process_listen_stop(session, event.payload, trace_id=trace_id))
        elif event.type == DeviceEventType.ABORT:
            self.audio.reset_capture(session)
            self._clear_partial_state(session)
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
            await self._send_tts_stop(
                session,
                aborted=True,
                reason=str(event.payload.get("reason") or "device_abort"),
                trace_id=trace_id,
            )
            await self._record_lifelog_event(
                session,
                "abort",
                payload={"trace_id": trace_id, "reason": event.payload.get("reason")},
            )
        elif event.type == DeviceEventType.IMAGE_READY:
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.THINKING)
            self._spawn(self._process_image_ready(session, event.payload, trace_id=trace_id))
        elif event.type == DeviceEventType.TELEMETRY:
            telemetry = event.payload if isinstance(event.payload, dict) else {}
            self.sessions.update_telemetry(session.device_id, session.session_id, telemetry)
            telemetry_structured: dict[str, Any] = {}
            if self.telemetry_normalize_enabled:
                telemetry_structured = normalize_telemetry_payload(telemetry, ts_ms=event.ts)
                if telemetry_structured:
                    self.sessions.update_metadata(
                        session.device_id,
                        session.session_id,
                        {
                            "telemetry_structured": telemetry_structured,
                            "telemetry_schema_version": str(
                                telemetry_structured.get("schema_version") or ""
                            ),
                        },
                    )
                    await self._persist_telemetry_sample(
                        session,
                        raw_telemetry=telemetry,
                        structured_telemetry=telemetry_structured,
                        trace_id=trace_id,
                        ts=event.ts,
                    )
            await self._send_ack(session, event.seq, trace_id=trace_id)
            event_payload: dict[str, Any] = {"trace_id": trace_id, "telemetry": telemetry}
            if telemetry_structured:
                event_payload["telemetry_structured"] = telemetry_structured
            await self._record_lifelog_event(
                session,
                "telemetry",
                payload=event_payload,
            )
        elif event.type == DeviceEventType.TOOL_RESULT:
            await self._handle_tool_result(session, event, trace_id=trace_id)
        elif event.type == DeviceEventType.ERROR:
            logger.warning(
                f"Device reported error {session.device_id}/{session.session_id}: {event.payload}"
            )
            await self._record_lifelog_event(
                session,
                "device_error",
                payload={"trace_id": trace_id, "error": event.payload},
                risk_level="P1",
            )
        else:
            logger.debug(f"Unsupported device event type: {event.type}")

    async def _ensure_device_authorized(
        self,
        session: DeviceSession,
        event: CanonicalEnvelope,
        *,
        trace_id: str,
    ) -> bool:
        if not self.device_auth_enabled:
            return True
        if event.type == DeviceEventType.HELLO:
            token = self._extract_device_token(event.payload)
            if not token:
                return await self._deny_device_event(
                    session,
                    trace_id=trace_id,
                    reason="missing_device_token",
                    event_type=event.type,
                )
            if self.lifelog is None or not hasattr(self.lifelog, "validate_device_auth"):
                return await self._deny_device_event(
                    session,
                    trace_id=trace_id,
                    reason="device_auth_service_unavailable",
                    event_type=event.type,
                )
            try:
                result = self.lifelog.validate_device_auth(
                    device_id=event.device_id,
                    device_token=token,
                    require_activated=self.require_activated_devices,
                    allow_unbound=self.allow_unbound_devices,
                )
            except Exception as e:
                logger.warning(f"device auth validate failed: {e}")
                return await self._deny_device_event(
                    session,
                    trace_id=trace_id,
                    reason="device_auth_error",
                    event_type=event.type,
                )
            if not isinstance(result, dict) or not bool(result.get("success")):
                reason = str(result.get("reason") or "device_auth_failed") if isinstance(result, dict) else "device_auth_failed"
                return await self._deny_device_event(
                    session,
                    trace_id=trace_id,
                    reason=reason,
                    event_type=event.type,
                )
            binding = result.get("binding")
            binding_map = binding if isinstance(binding, dict) else {}
            self.sessions.update_metadata(
                session.device_id,
                session.session_id,
                {
                    "auth_passed": True,
                    "auth_reason": str(result.get("reason") or "ok"),
                    "binding_status": str(binding_map.get("status") or ""),
                    "binding_user_id": str(binding_map.get("user_id") or ""),
                },
            )
            return True
        if bool(session.metadata.get("auth_passed")):
            return True
        return await self._deny_device_event(
            session,
            trace_id=trace_id,
            reason="unauthenticated_session",
            event_type=event.type,
        )

    async def _deny_device_event(
        self,
        session: DeviceSession,
        *,
        trace_id: str,
        reason: str,
        event_type: str,
    ) -> bool:
        logger.warning(
            f"device auth denied device_id={session.device_id} "
            f"session_id={session.session_id} reason={reason}"
        )
        self.sessions.update_metadata(
            session.device_id,
            session.session_id,
            {"auth_passed": False, "auth_reason": reason},
        )
        await self._send_session_command(
            session,
            DeviceCommandType.CLOSE,
            payload={"reason": reason},
            trace_id=trace_id,
        )
        self.sessions.close(session.device_id, session.session_id, reason=reason)
        await self._record_lifelog_event(
            session,
            "device_auth_denied",
            payload={
                "trace_id": trace_id,
                "reason": reason,
                "event_type": str(event_type),
            },
            risk_level="P1",
            confidence=1.0,
        )
        return False

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._inflight_tasks.add(task)
        task.add_done_callback(self._inflight_tasks.discard)

    def _make_session_command(
        self,
        session: DeviceSession,
        command_type: DeviceCommandType,
        payload: dict[str, Any] | None = None,
    ) -> CanonicalEnvelope:
        seq = self.sessions.next_outbound_seq(session.device_id, session.session_id)
        return make_command(
            command_type,
            device_id=session.device_id,
            session_id=session.session_id,
            seq=seq,
            payload=payload or {},
        )

    async def _send_session_command(
        self,
        session: DeviceSession,
        command_type: DeviceCommandType,
        payload: dict[str, Any] | None = None,
        *,
        trace_id: str,
    ) -> CanonicalEnvelope:
        command = self._make_session_command(session, command_type, payload=payload)
        self.metrics.record_command(command.type)
        logger.debug(
            f"hw-command type={command.type} trace_id={trace_id} "
            f"device_id={command.device_id} session_id={command.session_id} seq={command.seq}"
        )
        await self.adapter.send_command(command)
        return command

    async def _send_ack(self, session: DeviceSession, ack_seq: int, *, trace_id: str) -> None:
        await self._send_session_command(
            session,
            DeviceCommandType.ACK,
            payload={"ack_seq": ack_seq},
            trace_id=trace_id,
        )

    async def _on_hello(
        self,
        session: DeviceSession,
        event: CanonicalEnvelope,
        *,
        trace_id: str,
    ) -> None:
        metadata = event.payload.get("capabilities", {})
        if isinstance(metadata, dict):
            self.sessions.update_metadata(session.device_id, session.session_id, metadata)
        self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
        await self._send_session_command(
            session,
            DeviceCommandType.HELLO_ACK,
            payload={
                "runtime": "opencane-hardware",
                "protocol": event.version,
                "session_id": session.session_id,
                "ack_seq": event.seq,
            },
            trace_id=trace_id,
        )
        if self.digital_task and hasattr(self.digital_task, "flush_pending_updates"):
            self._spawn(self._flush_digital_task_pushes(session, trace_id=trace_id))

    async def _process_listen_stop(
        self,
        session: DeviceSession,
        payload: dict[str, Any],
        *,
        trace_id: str,
    ) -> None:
        self._clear_partial_state(session)
        turn_started_ms = int(time.time() * 1000)
        stt_started_ms = int(time.time() * 1000)
        transcript = await self.audio.finalize_capture(session, payload)
        stt_latency_ms = max(0, int(time.time() * 1000) - stt_started_ms)
        if transcript:
            await self._send_session_command(
                session,
                DeviceCommandType.STT_FINAL,
                payload={"text": transcript},
                trace_id=trace_id,
            )
        else:
            await self._send_tts_text(
                session,
                "I could not understand the audio. Please try again.",
                trace_id=trace_id,
                source="stt_error",
                confidence=1.0,
                risk_level="P2",
                context={"stage": "listen_stop"},
            )
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
            total_latency_ms = max(0, int(time.time() * 1000) - turn_started_ms)
            self.metrics.record_voice_turn(
                success=False,
                total_latency_ms=float(total_latency_ms),
                stt_latency_ms=float(stt_latency_ms),
                agent_latency_ms=0.0,
            )
            await self._record_lifelog_event(
                session,
                "voice_turn",
                payload={
                    "trace_id": trace_id,
                    "transcript": "",
                    "response": "",
                    "success": False,
                    "stt_latency_ms": int(stt_latency_ms),
                    "agent_latency_ms": 0,
                    "total_latency_ms": int(total_latency_ms),
                },
                risk_level="P2",
            )
            return

        if self._should_route_to_digital_task(transcript, payload):
            routed = await self._execute_digital_task_from_voice(
                session,
                transcript=transcript,
                trace_id=trace_id,
            )
            if routed:
                self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
                total_latency_ms = max(0, int(time.time() * 1000) - turn_started_ms)
                self.metrics.record_voice_turn(
                    success=True,
                    total_latency_ms=float(total_latency_ms),
                    stt_latency_ms=float(stt_latency_ms),
                    agent_latency_ms=0.0,
                )
                await self._record_lifelog_event(
                    session,
                    "digital_task_turn",
                    payload={
                        "trace_id": trace_id,
                        "transcript": transcript,
                        "routed": True,
                        "stt_latency_ms": int(stt_latency_ms),
                        "agent_latency_ms": 0,
                        "total_latency_ms": int(total_latency_ms),
                    },
                    confidence=0.8,
                )
                return
        tool_allowlist, tool_denylist, policy_context = await self._resolve_agent_tool_policy(session)
        runtime_context = self._build_agent_runtime_context(
            session,
            trace_id=trace_id,
            transcript=transcript,
            policy_context=policy_context,
        )
        agent_started_ms = int(time.time() * 1000)
        response = await self.agent_loop.process_direct(
            transcript,
            session_key=f"hardware:{session.device_id}:{session.session_id}",
            channel="hardware",
            chat_id=session.device_id,
            allowed_tool_names=tool_allowlist,
            blocked_tool_names=tool_denylist,
            message_metadata={"runtime_context": runtime_context},
        )
        agent_latency_ms = max(0, int(time.time() * 1000) - agent_started_ms)
        await self._send_tts_text(
            session,
            response or "",
            trace_id=trace_id,
            source="agent_reply",
            confidence=0.75,
            risk_level="P3",
            context={"transcript": transcript},
        )
        self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
        total_latency_ms = max(0, int(time.time() * 1000) - turn_started_ms)
        self.metrics.record_voice_turn(
            success=True,
            total_latency_ms=float(total_latency_ms),
            stt_latency_ms=float(stt_latency_ms),
            agent_latency_ms=float(agent_latency_ms),
        )
        await self._record_lifelog_event(
            session,
            "voice_turn",
            payload={
                "trace_id": trace_id,
                "transcript": transcript,
                "response": (response or "")[:1000],
                "success": True,
                "stt_latency_ms": int(stt_latency_ms),
                "agent_latency_ms": int(agent_latency_ms),
                "total_latency_ms": int(total_latency_ms),
            },
            confidence=0.7,
        )

    async def _process_image_ready(
        self,
        session: DeviceSession,
        payload: dict[str, Any],
        *,
        trace_id: str,
    ) -> None:
        await self._ingest_lifelog_image(session, payload, trace_id=trace_id)
        if self.vision_service is None:
            await self._send_tts_text(
                session,
                "Vision service is not available.",
                trace_id=trace_id,
                source="vision_reply",
                confidence=1.0,
                risk_level="P2",
                context={"reason": "vision unavailable"},
            )
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
            await self._record_lifelog_event(
                session,
                "image_turn",
                payload={"trace_id": trace_id, "success": False, "reason": "vision unavailable"},
                risk_level="P2",
            )
            return
        result = await self.vision_service.analyze_payload(payload)
        answer = result.get("result", "") if isinstance(result, dict) else str(result)
        if not answer:
            answer = "I could not analyze the image."
        vision_confidence = _to_float(result.get("confidence") if isinstance(result, dict) else None, default=0.7)
        vision_risk = str(result.get("risk_level") if isinstance(result, dict) else "") or "P2"
        await self._send_tts_text(
            session,
            answer,
            trace_id=trace_id,
            source="vision_reply",
            confidence=vision_confidence,
            risk_level=vision_risk,
            context={
                "question": payload.get("question") or payload.get("prompt") or "",
                "vision_success": bool(result.get("success")) if isinstance(result, dict) else True,
                "proactive_hint": "如需，我可以继续补充左右障碍与可通行方向。",
            },
        )
        self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
        await self._record_lifelog_event(
            session,
            "image_turn",
            payload={
                "trace_id": trace_id,
                "question": payload.get("question") or payload.get("prompt") or "",
                "result": answer[:1000],
                "success": bool(answer),
            },
            risk_level=vision_risk,
            confidence=vision_confidence,
        )

    async def _send_tts_text(
        self,
        session: DeviceSession,
        text: str,
        *,
        trace_id: str,
        source: str = "runtime",
        confidence: float = 1.0,
        risk_level: str = "P3",
        context: dict[str, Any] | None = None,
        apply_safety: bool = True,
    ) -> None:
        text = (text or "").strip()
        if text and apply_safety:
            text = await self._apply_safety_policy_text(
                session,
                text,
                trace_id=trace_id,
                source=source,
                confidence=confidence,
                risk_level=risk_level,
                context=context,
            )
        if text:
            text, should_speak = await self._apply_interaction_policy_text(
                session,
                text,
                trace_id=trace_id,
                source=source,
                confidence=confidence,
                risk_level=risk_level,
                context=context,
            )
            if not should_speak:
                self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
                await self._send_tts_stop(
                    session,
                    aborted=False,
                    trace_id=trace_id,
                    reason="interaction_policy_silent",
                )
                return
        if not text:
            await self._send_tts_stop(session, aborted=False, trace_id=trace_id)
            return
        if self.tts_mode == "server_audio":
            sent = await self._send_tts_audio(
                session,
                text,
                trace_id=trace_id,
            )
            if sent:
                return

        self.sessions.update_state(session.device_id, session.session_id, ConnectionState.SPEAKING)
        await self._send_session_command(
            session,
            DeviceCommandType.TTS_START,
            payload={"text": text[:80]},
            trace_id=trace_id,
        )
        for chunk in self._chunk_text(text, chunk_size=220):
            await self._send_session_command(
                session,
                DeviceCommandType.TTS_CHUNK,
                payload={"text": chunk},
                trace_id=trace_id,
            )
        await self._send_tts_stop(session, aborted=False, trace_id=trace_id)

    async def _send_tts_audio(
        self,
        session: DeviceSession,
        text: str,
        *,
        trace_id: str,
    ) -> bool:
        audio_data = await self._synthesize_tts_audio(text)
        if audio_data is None:
            return False
        audio_bytes, metadata = audio_data
        if not audio_bytes:
            return False

        self.sessions.update_state(session.device_id, session.session_id, ConnectionState.SPEAKING)
        preview = text[:80]
        await self._send_session_command(
            session,
            DeviceCommandType.TTS_START,
            payload={
                "text": preview,
                "mode": "server_audio",
                "encoding": str(metadata.get("encoding") or ""),
            },
            trace_id=trace_id,
        )
        for chunk in self._chunk_bytes(audio_bytes, chunk_size=self.tts_audio_chunk_bytes):
            chunk_payload = {
                "audio_b64": base64.b64encode(chunk).decode("ascii"),
                "encoding": str(metadata.get("encoding") or "wav"),
            }
            sample_rate_hz = metadata.get("sample_rate_hz")
            if isinstance(sample_rate_hz, int) and sample_rate_hz > 0:
                chunk_payload["sample_rate_hz"] = sample_rate_hz
            await self._send_session_command(
                session,
                DeviceCommandType.TTS_CHUNK,
                payload=chunk_payload,
                trace_id=trace_id,
            )
        await self._send_tts_stop(session, aborted=False, trace_id=trace_id)
        return True

    async def _synthesize_tts_audio(
        self,
        text: str,
    ) -> tuple[bytes, dict[str, Any]] | None:
        synthesizer = self.tts_synthesizer
        if synthesizer is None or not hasattr(synthesizer, "synthesize"):
            logger.warning("server_audio requested but no synthesizer configured")
            return None
        try:
            result = await synthesizer.synthesize(text)
        except Exception as e:
            logger.warning(f"server_audio synthesize failed: {e}")
            return None
        if result is None:
            return None

        if isinstance(result, bytes):
            return result, {"encoding": "wav", "sample_rate_hz": 16000}

        if isinstance(result, dict):
            audio_b64 = result.get("audio_b64")
            if audio_b64:
                try:
                    audio = base64.b64decode(str(audio_b64))
                except Exception:
                    return None
            else:
                audio = bytes(result.get("audio") or b"")
            if not audio:
                return None
            return audio, {
                "encoding": str(result.get("encoding") or "wav"),
                "sample_rate_hz": _to_int(result.get("sample_rate_hz"), default=16000),
            }

        audio = bytes(getattr(result, "audio", b"") or b"")
        if not audio:
            return None
        return audio, {
            "encoding": str(getattr(result, "encoding", "wav")),
            "sample_rate_hz": _to_int(getattr(result, "sample_rate_hz", 16000), default=16000),
        }

    async def _apply_safety_policy_text(
        self,
        session: DeviceSession,
        text: str,
        *,
        trace_id: str,
        source: str,
        confidence: float,
        risk_level: str,
        context: dict[str, Any] | None,
    ) -> str:
        policy = self.safety_policy
        if policy is None or not hasattr(policy, "evaluate"):
            return text
        try:
            raw = policy.evaluate(
                text=text,
                source=source,
                confidence=confidence,
                risk_level=risk_level,
                context=context or {},
            )
            if hasattr(raw, "to_dict"):
                decision = raw.to_dict()
            elif isinstance(raw, dict):
                decision = dict(raw)
            else:
                return text
        except Exception as e:
            logger.debug(f"safety policy evaluate failed: {e}")
            return text

        output_text = str(decision.get("text") or text).strip() or text
        final_risk = str(decision.get("risk_level") or risk_level or "P3")
        final_confidence = _to_float(decision.get("confidence"), default=confidence)
        downgraded = bool(decision.get("downgraded"))
        reason = str(decision.get("reason") or "")
        flags = decision.get("flags")
        if not isinstance(flags, list):
            flags = []
        rule_ids = decision.get("rule_ids")
        if not isinstance(rule_ids, list):
            rule_ids = []
        evidence = decision.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}

        self._safety_applied += 1
        if downgraded:
            self._safety_downgraded += 1

        await self._record_lifelog_event(
            session,
            "safety_policy",
            payload={
                "trace_id": trace_id,
                "source": source,
                "reason": reason,
                "flags": flags,
                "policy_version": str(decision.get("policy_version") or "unknown"),
                "rule_ids": [str(rule_id) for rule_id in rule_ids],
                "evidence": dict(evidence),
                "input_text": _shorten(text, 300),
                "output_text": _shorten(output_text, 300),
                "input_risk_level": str(risk_level),
                "output_risk_level": final_risk,
                "downgraded": downgraded,
                "context": dict(context or {}),
            },
            risk_level=final_risk,
            confidence=final_confidence,
        )
        return output_text

    async def _apply_interaction_policy_text(
        self,
        session: DeviceSession,
        text: str,
        *,
        trace_id: str,
        source: str,
        confidence: float,
        risk_level: str,
        context: dict[str, Any] | None,
    ) -> tuple[str, bool]:
        policy = self.interaction_policy
        if policy is None or not hasattr(policy, "evaluate"):
            return text, True
        try:
            raw = policy.evaluate(
                text=text,
                source=source,
                confidence=confidence,
                risk_level=risk_level,
                context=context or {},
                speak=True,
            )
            if hasattr(raw, "to_dict"):
                decision = raw.to_dict()
            elif isinstance(raw, dict):
                decision = dict(raw)
            else:
                return text, True
        except Exception as e:
            logger.debug(f"interaction policy evaluate failed: {e}")
            return text, True

        output_text = str(decision.get("text") or text).strip() or text
        should_speak = bool(decision.get("should_speak", True))
        final_risk = str(decision.get("risk_level") or risk_level or "P3")
        final_confidence = _to_float(decision.get("confidence"), default=confidence)
        reason = str(decision.get("reason") or "")
        flags = decision.get("flags")
        if not isinstance(flags, list):
            flags = []

        self._interaction_applied += 1
        if not should_speak:
            self._interaction_suppressed += 1

        await self._record_lifelog_event(
            session,
            "interaction_policy",
            payload={
                "trace_id": trace_id,
                "source": source,
                "reason": reason,
                "flags": [str(item) for item in flags],
                "policy_version": str(decision.get("policy_version") or "unknown"),
                "input_text": _shorten(text, 300),
                "output_text": _shorten(output_text, 300),
                "should_speak": should_speak,
                "risk_level": final_risk,
                "context": dict(context or {}),
            },
            risk_level=final_risk,
            confidence=final_confidence,
        )
        return output_text, should_speak

    async def _execute_digital_task_from_voice(
        self,
        session: DeviceSession,
        *,
        transcript: str,
        trace_id: str,
    ) -> bool:
        service = self.digital_task
        if service is None or not hasattr(service, "execute"):
            return False
        payload = {
            "session_id": session.session_id,
            "device_id": session.device_id,
            "goal": transcript,
            "notify": True,
            "speak": True,
            "interrupt_previous": True,
            "source": "voice_intent",
            "trace_id": trace_id,
        }
        try:
            result = await service.execute(payload)
        except Exception as e:
            logger.warning(f"digital task route failed: {e}")
            await self._send_tts_text(
                session,
                "数字任务创建失败，请稍后重试。",
                trace_id=trace_id,
                source="digital_task_route",
                confidence=1.0,
                risk_level="P2",
            )
            return True
        if result.get("success"):
            task = result.get("task")
            task_id = str(task.get("task_id") if isinstance(task, dict) else "")
            logger.info(
                f"digital task routed from voice device_id={session.device_id} "
                f"session_id={session.session_id} task_id={task_id}"
            )
            return True
        err = str(result.get("error") or "数字任务创建失败")
        await self._send_tts_text(
            session,
            f"{err}。",
            trace_id=trace_id,
            source="digital_task_route",
            confidence=1.0,
            risk_level="P2",
        )
        return True

    async def _flush_digital_task_pushes(self, session: DeviceSession, *, trace_id: str) -> None:
        service = self.digital_task
        if service is None or not hasattr(service, "flush_pending_updates"):
            return
        try:
            result = await service.flush_pending_updates(
                device_id=session.device_id,
                session_id=session.session_id,
                limit=20,
            )
            if isinstance(result, dict):
                logger.debug(
                    f"digital-task flush trace_id={trace_id} device_id={session.device_id} "
                    f"session_id={session.session_id} sent={result.get('sent')} retry={result.get('retry')}"
                )
        except Exception as e:
            logger.debug(f"digital task flush failed: {e}")

    async def _send_tts_stop(
        self,
        session: DeviceSession,
        *,
        aborted: bool,
        trace_id: str,
        reason: str = "",
    ) -> None:
        payload: dict[str, Any] = {"aborted": bool(aborted)}
        if reason:
            payload["reason"] = str(reason)
        await self._send_session_command(
            session,
            DeviceCommandType.TTS_STOP,
            payload=payload,
            trace_id=trace_id,
        )

    async def push_task_update(
        self,
        *,
        task_id: str,
        status: str,
        message: str,
        device_id: str,
        session_id: str = "",
        speak: bool = True,
        extra: dict[str, Any] | None = None,
        trace_id: str = "digital-task",
    ) -> bool:
        """Push digital task status to one online device session."""
        device_id = str(device_id or "").strip()
        if not device_id:
            return False
        session = self.sessions.get(device_id, session_id) if session_id else self.sessions.get_latest(device_id)
        if session is None:
            return False

        raw_message = str(message or "").strip()
        safe_message = raw_message
        extra_payload = extra if isinstance(extra, dict) else {}
        default_conf = self._status_default_confidence(status)
        default_risk = self._status_default_risk(status)
        task_confidence = _to_float(extra_payload.get("confidence"), default=default_conf)
        task_risk = str(extra_payload.get("risk_level") or default_risk)
        if raw_message:
            safe_message = await self._apply_safety_policy_text(
                session,
                raw_message,
                trace_id=trace_id,
                source="task_update",
                confidence=task_confidence,
                risk_level=task_risk,
                context={
                    "task_id": task_id,
                    "status": status,
                    "event": str(extra_payload.get("event") or ""),
                    "priority": str(extra_payload.get("priority") or ""),
                },
            )

        payload = {
            "task_id": str(task_id),
            "status": str(status),
            "message": str(safe_message or ""),
        }
        if extra:
            payload["extra"] = dict(extra)
        await self._send_session_command(
            session,
            DeviceCommandType.TASK_UPDATE,
            payload=payload,
            trace_id=trace_id,
        )
        if speak and safe_message:
            await self._send_tts_text(
                session,
                safe_message,
                trace_id=trace_id,
                source="task_update",
                confidence=task_confidence,
                risk_level=task_risk,
                context={
                    "task_id": task_id,
                    "status": status,
                    "event": str(extra_payload.get("event") or ""),
                    "priority": str(extra_payload.get("priority") or ""),
                },
                apply_safety=False,
            )
            self.sessions.update_state(session.device_id, session.session_id, ConnectionState.READY)
        return True

    async def dispatch_device_operation(
        self,
        *,
        device_id: str,
        op_type: str,
        payload: dict[str, Any],
        session_id: str = "",
        trace_id: str = "device-op",
    ) -> dict[str, Any]:
        device = str(device_id or "").strip()
        if not device:
            return {"success": False, "error": "device_id is required", "error_code": "bad_request"}
        op_name = str(op_type or "").strip().lower()
        command_type = _operation_command_type(op_name)
        if command_type is None:
            return {"success": False, "error": f"unsupported op_type: {op_type}", "error_code": "bad_request"}
        body = payload if isinstance(payload, dict) else {}
        session = self.sessions.get(device, session_id) if session_id else self.sessions.get_latest(device)
        if session is None:
            return {"success": False, "error": "device session not found", "error_code": "not_found"}
        command = await self._send_session_command(
            session,
            command_type,
            payload=dict(body),
            trace_id=trace_id,
        )
        await self._record_lifelog_event(
            session,
            "device_operation_dispatch",
            payload={
                "trace_id": trace_id,
                "op_type": op_name,
                "command_type": str(command_type),
                "seq": int(command.seq),
                "payload": dict(body),
            },
            confidence=1.0,
        )
        return {
            "success": True,
            "device_id": session.device_id,
            "session_id": session.session_id,
            "op_type": op_name,
            "command_type": str(command_type),
            "seq": int(command.seq),
        }

    @staticmethod
    def _chunk_text(text: str, chunk_size: int) -> Iterable[str]:
        if len(text) <= chunk_size:
            return [text]
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    @staticmethod
    def _chunk_bytes(data: bytes, chunk_size: int) -> Iterable[bytes]:
        if len(data) <= chunk_size:
            return [data]
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def abort(self, device_id: str, reason: str = "manual_abort") -> bool:
        session = self.sessions.get_latest(device_id)
        if not session:
            return False
        self.audio.reset_capture(session)
        self._clear_partial_state(session)
        self.sessions.update_state(device_id, session.session_id, ConnectionState.READY)
        await self._send_session_command(
            session,
            DeviceCommandType.TTS_STOP,
            payload={"aborted": True, "reason": reason},
            trace_id="manual-abort",
        )
        return True

    def get_device_status(self, device_id: str) -> dict[str, Any] | None:
        return self.sessions.status(device_id)

    def get_runtime_status(self) -> dict[str, Any]:
        digital_task_stats: dict[str, Any] = {}
        if self.digital_task is not None and hasattr(self.digital_task, "stats_snapshot"):
            with contextlib.suppress(Exception):
                digital_task_stats = self.digital_task.stats_snapshot()
        lifelog_status: dict[str, Any] = {}
        if self.lifelog is not None and hasattr(self.lifelog, "status_snapshot"):
            with contextlib.suppress(Exception):
                value = self.lifelog.status_snapshot()
                lifelog_status = dict(value) if isinstance(value, dict) else {}
        safety_enabled = bool(self.safety_policy) and bool(getattr(self.safety_policy, "enabled", True))
        return {
            "adapter": self.adapter.name,
            "transport": self.adapter.transport,
            "running": self._running,
            "metrics": self.metrics.snapshot(),
            "lifelog": lifelog_status,
            "digital_task": digital_task_stats,
            "safety": {
                "enabled": safety_enabled,
                "applied": self._safety_applied,
                "downgraded": self._safety_downgraded,
            },
            "interaction": {
                "enabled": bool(self.interaction_policy)
                and bool(getattr(self.interaction_policy, "enabled", True)),
                "applied": self._interaction_applied,
                "suppressed": self._interaction_suppressed,
            },
            "devices": self.sessions.all_status(),
        }

    async def _maybe_emit_stt_partial(
        self,
        session: DeviceSession,
        partial_text: str,
        *,
        trace_id: str,
    ) -> None:
        text = str(partial_text or "").strip()
        if not text:
            return
        key = (session.device_id, session.session_id)
        now_ms = int(time.time() * 1000)
        last = self._stt_partial_state.get(key)
        if last:
            last_text, last_ts = last
            if text == last_text and now_ms - last_ts < 1000:
                return
            growth = len(text) - len(last_text)
            if text.startswith(last_text) and growth >= 0 and growth < 3 and now_ms - last_ts < 250:
                return
        self._stt_partial_state[key] = (text, now_ms)
        await self._send_session_command(
            session,
            DeviceCommandType.STT_PARTIAL,
            payload={"text": text},
            trace_id=trace_id,
        )

    def _clear_partial_state(self, session: DeviceSession) -> None:
        self._stt_partial_state.pop((session.device_id, session.session_id), None)

    @staticmethod
    def _trace_id_for_event(event: CanonicalEnvelope) -> str:
        payload = event.payload if isinstance(event.payload, dict) else {}
        trace = payload.get("trace_id") or payload.get("traceId") or event.msg_id
        return str(trace)

    @staticmethod
    def _extract_device_token(payload: dict[str, Any] | None) -> str:
        data = payload if isinstance(payload, dict) else {}
        token = str(
            data.get("device_token")
            or data.get("deviceToken")
            or data.get("auth_token")
            or data.get("authToken")
            or data.get("token")
            or data.get("authorization")
            or ""
        ).strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    async def _resolve_agent_tool_policy(
        self,
        session: DeviceSession,
    ) -> tuple[set[str] | None, set[str] | None, dict[str, Any]]:
        client = self.control_plane_client
        if client is None or not hasattr(client, "fetch_device_policy"):
            return None, None, {"enabled": False, "source": "disabled"}
        try:
            raw = await client.fetch_device_policy(device_id=session.device_id)
        except Exception as e:
            logger.debug(f"control-plane device policy fetch failed: {e}")
            return None, None, {
                "enabled": True,
                "source": "error",
                "warning": str(e),
            }
        if not isinstance(raw, dict):
            return None, None, {
                "enabled": True,
                "source": "invalid_response",
                "warning": "device policy result is not a dict",
            }
        source = str(raw.get("source") or "")
        warning = str(raw.get("warning") or "")
        if not bool(raw.get("success")):
            return None, None, {
                "enabled": True,
                "source": source or "failed",
                "warning": warning or str(raw.get("error") or "device policy fetch failed"),
            }
        data = raw.get("data")
        policy = data if isinstance(data, dict) else {}
        allow_raw = policy.get("allow_tools")
        if allow_raw is None:
            allow_raw = policy.get("allowed_tools")
        deny_raw = policy.get("deny_tools")
        if deny_raw is None:
            deny_raw = policy.get("blocked_tools")
        allow = _normalize_tool_list(allow_raw)
        deny = _normalize_tool_list(deny_raw)
        if allow is not None and deny:
            allow = {name for name in allow if name not in deny}
        return allow, deny, {
            "enabled": True,
            "source": source or "unknown",
            "warning": warning,
            "allow_tools": sorted(allow) if allow is not None else None,
            "deny_tools": sorted(deny) if deny else [],
        }

    def _build_agent_runtime_context(
        self,
        session: DeviceSession,
        *,
        trace_id: str,
        transcript: str,
        policy_context: dict[str, Any],
    ) -> dict[str, Any]:
        context = {
            "device_id": session.device_id,
            "session_id": session.session_id,
            "state": session.state.value,
            "trace_id": str(trace_id),
            "transcript": _shorten(str(transcript or ""), 280),
            "telemetry": dict(session.telemetry),
            "session_metadata": dict(session.metadata),
            "tool_policy": dict(policy_context or {}),
        }
        telemetry_structured = session.metadata.get("telemetry_structured")
        if isinstance(telemetry_structured, dict):
            context["telemetry_structured"] = dict(telemetry_structured)
        return context

    @staticmethod
    def _resolve_session_persistence_store(lifelog_service: Any | None) -> Any | None:
        if lifelog_service is None:
            return None
        if hasattr(lifelog_service, "upsert_device_session"):
            return lifelog_service
        store = getattr(lifelog_service, "store", None)
        if store is None:
            return None
        if hasattr(store, "upsert_device_session"):
            return store
        db = getattr(store, "db", None)
        if db is not None and hasattr(db, "upsert_device_session"):
            return db
        return None

    async def _record_lifelog_event(
        self,
        session: DeviceSession,
        event_type: str,
        *,
        payload: dict[str, Any],
        risk_level: str = "P3",
        confidence: float = 0.0,
    ) -> None:
        if self.lifelog is None or not hasattr(self.lifelog, "record_runtime_event"):
            return
        try:
            self.lifelog.record_runtime_event(
                session_id=session.session_id,
                event_type=event_type,
                payload=payload,
                risk_level=risk_level,
                confidence=confidence,
            )
        except Exception as e:
            logger.debug(f"lifelog record runtime event failed: {e}")

    async def _persist_telemetry_sample(
        self,
        session: DeviceSession,
        *,
        raw_telemetry: dict[str, Any],
        structured_telemetry: dict[str, Any],
        trace_id: str,
        ts: int,
    ) -> None:
        if not self.telemetry_persist_samples_enabled:
            return
        if self.lifelog is None or not hasattr(self.lifelog, "append_telemetry_sample"):
            return
        payload = {
            "device_id": session.device_id,
            "session_id": session.session_id,
            "schema_version": str(structured_telemetry.get("schema_version") or ""),
            "sample": dict(structured_telemetry),
            "raw": dict(raw_telemetry),
            "trace_id": str(trace_id),
            "ts": int(ts),
        }
        try:
            result = self.lifelog.append_telemetry_sample(payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.debug(f"telemetry sample persistence failed: {e}")

    async def _handle_tool_result(
        self,
        session: DeviceSession,
        event: CanonicalEnvelope,
        *,
        trace_id: str,
    ) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        await self._send_ack(session, event.seq, trace_id=trace_id)
        operation_id = str(
            payload.get("operation_id")
            or payload.get("operationId")
            or payload.get("op_id")
            or ""
        ).strip()
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("name") or "").strip()
        explicit_success = _to_bool(payload.get("success"), default=None)
        error = str(payload.get("error") or "").strip()
        success = bool(explicit_success) if explicit_success is not None else not bool(error)
        result = payload.get("result")
        result_map = result if isinstance(result, dict) else {}
        if not result_map and result is not None and result != "":
            result_map = {"value": result}

        event_payload: dict[str, Any] = {
            "trace_id": trace_id,
            "operation_id": operation_id,
            "tool_name": tool_name,
            "success": success,
            "result": result_map,
            "error": error,
        }
        risk_level = "P3"
        if not success and error:
            risk_level = "P2"
        if not self.tool_result_enabled:
            event_payload["accepted"] = False
            event_payload["reason"] = "feature_disabled"
            await self._record_lifelog_event(
                session,
                "tool_result_ignored",
                payload=event_payload,
                risk_level="P3",
                confidence=1.0,
            )
            return

        event_payload["accepted"] = True
        await self._record_lifelog_event(
            session,
            "tool_result",
            payload=event_payload,
            risk_level=risk_level,
            confidence=0.9 if success else 0.7,
        )
        if self.tool_result_mark_device_operation_enabled and operation_id:
            await self._mark_device_operation_from_tool_result(
                operation_id=operation_id,
                success=success,
                result=result_map,
                error=error,
                session=session,
            )

    async def _mark_device_operation_from_tool_result(
        self,
        *,
        operation_id: str,
        success: bool,
        result: dict[str, Any],
        error: str,
        session: DeviceSession,
    ) -> None:
        if self.lifelog is None or not hasattr(self.lifelog, "device_operation_mark"):
            return
        status = "acked" if success else "failed"
        payload = {
            "operation_id": str(operation_id),
            "status": status,
            "result": dict(result),
            "error": str(error or ""),
            "session_id": session.session_id,
            "acked_at_ms": int(time.time() * 1000) if success else 0,
        }
        try:
            raw = self.lifelog.device_operation_mark(payload)
            value = await raw if asyncio.iscoroutine(raw) else raw
            if isinstance(value, dict) and not bool(value.get("success", True)):
                logger.debug(f"device operation mark failed: {value.get('error')}")
        except Exception as e:
            logger.debug(f"device operation mark from tool_result failed: {e}")

    async def _ingest_lifelog_image(
        self,
        session: DeviceSession,
        payload: dict[str, Any],
        *,
        trace_id: str,
    ) -> None:
        if self.lifelog is None or not hasattr(self.lifelog, "enqueue_image"):
            return
        image_base64 = payload.get("image_base64") or payload.get("imageBase64") or payload.get("image")
        if not image_base64:
            return
        request = {
            "session_id": session.session_id,
            "image_base64": image_base64,
            "question": payload.get("question") or payload.get("prompt") or "",
            "mime": payload.get("mime") or "image/jpeg",
            "metadata": {"trace_id": trace_id, "source": "hardware_runtime"},
            "ts": payload.get("ts"),
        }
        try:
            await self.lifelog.enqueue_image(request)
        except Exception as e:
            logger.debug(f"lifelog image ingest failed: {e}")

    @staticmethod
    def _status_default_confidence(status: str) -> float:
        name = str(status or "").strip().lower()
        if name in {"success", "running", "pending"}:
            return 0.9
        if name in {"failed", "timeout", "canceled"}:
            return 0.8
        return 0.75

    @staticmethod
    def _status_default_risk(status: str) -> str:
        name = str(status or "").strip().lower()
        if name in {"failed", "timeout"}:
            return "P2"
        return "P3"

    @staticmethod
    def _should_route_to_digital_task(transcript: str, payload: dict[str, Any]) -> bool:
        if str(payload.get("intent") or "").strip().lower() == "digital_task":
            return True
        if bool(payload.get("digital_task")):
            return True
        text = str(transcript or "").strip().lower()
        if not text:
            return False
        prefixes = (
            "帮我",
            "请帮我",
            "替我",
            "请替我",
            "帮我去",
            "帮我查",
            "帮我预约",
            "帮我挂号",
            "帮我订",
            "帮我买",
        )
        if any(text.startswith(prefix.lower()) for prefix in prefixes):
            return True
        keywords = (
            "help me",
            "book",
            "reserve",
            "register",
            "schedule",
            "order",
        )
        return any(word in text for word in keywords)


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _shorten(text: str, max_chars: int) -> str:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _operation_command_type(op_type: str) -> DeviceCommandType | None:
    mapping = {
        "set_config": DeviceCommandType.SET_CONFIG,
        "tool_call": DeviceCommandType.TOOL_CALL,
        "ota_plan": DeviceCommandType.OTA_PLAN,
    }
    return mapping.get(str(op_type or "").strip().lower())


def _normalize_tool_list(value: Any) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    output: set[str] = set()
    for item in value:
        name = str(item or "").strip()
        if name:
            output.add(name)
    return output

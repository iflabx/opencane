"""EC600-focused adapters and MQTT transport integration."""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from opencane.config.schema import HardwareMQTTConfig
from opencane.hardware.adapter.base import GatewayAdapter
from opencane.hardware.adapter.mock_adapter import MockAdapter
from opencane.hardware.protocol import (
    CanonicalEnvelope,
    DeviceCommandType,
    DeviceEventType,
    make_event,
)

_SENTINEL = object()


class EC600Adapter(MockAdapter):
    """Parser shim for EC600 modem traffic."""

    name = "ec600"
    transport = "mqtt"

    def __init__(self, packet_magic: int = 0xA1) -> None:
        super().__init__()
        self.packet_magic = packet_magic

    async def ingest_control(
        self,
        raw: str | bytes | dict[str, Any],
        *,
        device_id: str | None = None,
        session_id: str | None = None,
    ) -> CanonicalEnvelope:
        """Parse raw control payload into canonical envelope and enqueue it."""
        if isinstance(raw, dict):
            data = raw
        else:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            data = json.loads(text)
        envelope = CanonicalEnvelope.from_dict(
            data,
            default_device_id=device_id,
            default_session_id=session_id,
        )
        await self.inject_event(envelope)
        return envelope


class EC600MQTTAdapter(GatewayAdapter):
    """MQTT adapter for EC600-like cellular modules."""

    name = "ec600"
    transport = "mqtt"

    def __init__(
        self,
        config: HardwareMQTTConfig,
        *,
        packet_magic: int = 0xA1,
    ) -> None:
        self.config = config
        self.packet_magic = packet_magic
        self._running = False
        self._queue: asyncio.Queue[CanonicalEnvelope | object] = asyncio.Queue()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt_client: Any | None = None
        self._session_by_device: dict[str, str] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._control_replay_window = max(1, self.config.control_replay_window)
        self._offline_control_buffer = max(1, self.config.offline_control_buffer)
        self._control_window_by_device: dict[str, deque[tuple[int, str, str, int]]] = defaultdict(
            lambda: deque(maxlen=self._control_replay_window)
        )
        self._pending_control_by_device: dict[str, deque[tuple[int, str, str, int]]] = defaultdict(
            lambda: deque(maxlen=self._offline_control_buffer)
        )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._setup_client()
        if self._mqtt_client is None:
            raise RuntimeError("MQTT client is not available")
        self._mqtt_client.connect_async(
            host=self.config.host,
            port=self.config.port,
            keepalive=max(10, self.config.keepalive_seconds),
        )
        self._mqtt_client.loop_start()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._mqtt_client is not None:
            try:
                self._mqtt_client.disconnect()
            except Exception:
                pass
            try:
                self._mqtt_client.loop_stop()
            except Exception:
                pass
            self._mqtt_client = None
        self._connected = False
        self._session_by_device.clear()
        self._control_window_by_device.clear()
        self._pending_control_by_device.clear()
        await self._queue.put(_SENTINEL)

    async def recv_events(self) -> AsyncIterator[CanonicalEnvelope]:
        while self._running:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield item

    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        if self._mqtt_client is None:
            raise RuntimeError("MQTT client is not initialized")

        topic = self._render_topic(self.config.down_control_topic_template, cmd.device_id)
        payload = json.dumps(cmd.to_dict(), ensure_ascii=False)
        qos = self.config.qos_control
        is_control_json = True

        if cmd.type == DeviceCommandType.TTS_CHUNK and cmd.payload.get("audio_b64"):
            try:
                audio = base64.b64decode(str(cmd.payload["audio_b64"]))
            except Exception:
                logger.warning("Invalid audio_b64 in tts_chunk payload, falling back to control JSON")
            else:
                is_control_json = False
                topic = self._render_topic(self.config.down_audio_topic_template, cmd.device_id)
                qos = self.config.qos_audio
                payload = self._build_audio_packet(
                    audio,
                    seq=cmd.seq,
                    timestamp=cmd.ts,
                )

        if not self._connected:
            if is_control_json and isinstance(payload, str):
                self._buffer_pending_control(cmd.device_id, cmd.seq, topic, payload, qos)
            logger.warning(f"{self.name} MQTT adapter is disconnected, control command buffered or dropped")
            return

        result = self._mqtt_client.publish(topic, payload=payload, qos=qos)
        if result.rc != 0:
            logger.warning(f"MQTT publish failed rc={result.rc} topic={topic}")
            if is_control_json and isinstance(payload, str):
                self._buffer_pending_control(cmd.device_id, cmd.seq, topic, payload, qos)
            return
        if is_control_json and isinstance(payload, str):
            self._remember_control_window(cmd.device_id, cmd.seq, topic, payload, qos)

    def _setup_client(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as e:
            raise RuntimeError(
                f"paho-mqtt is required for {self.__class__.__name__}. Install with `pip install paho-mqtt`."
            ) from e

        client = mqtt.Client(client_id=self.config.client_id, clean_session=True)
        if self.config.username:
            client.username_pw_set(
                username=self.config.username,
                password=self.config.password or None,
            )
        if self.config.tls_enabled:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        client.reconnect_delay_set(
            min_delay=max(1, self.config.reconnect_min_seconds),
            max_delay=max(self.config.reconnect_min_seconds, self.config.reconnect_max_seconds),
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._mqtt_client = client

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        rc: Any,
        properties: Any | None = None,
    ) -> None:
        del userdata, flags, properties
        try:
            rc_int = int(rc) if rc is not None else -1
        except Exception:
            rc_int = -1
        self._connected = rc_int == 0
        if rc_int != 0:
            logger.warning(f"MQTT connect failed rc={rc_int}")
            return
        logger.info(f"{self.name} MQTT connected to {self.config.host}:{self.config.port}")
        client.subscribe(self.config.up_control_topic, qos=self.config.qos_control)
        client.subscribe(self.config.up_audio_topic, qos=self.config.qos_audio)

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        *args: Any,
    ) -> None:
        del client, userdata
        # paho v1: (rc), paho v2: (disconnect_flags, reason_code, properties)
        rc = args[0] if len(args) == 1 else (args[1] if len(args) >= 2 else None)
        try:
            rc_int = int(rc) if rc is not None else -1
        except Exception:
            rc_int = -1
        self._connected = False
        if self._running:
            logger.warning(f"{self.name} MQTT disconnected rc={rc_int}")

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        del client, userdata
        event = self._parse_incoming_message(msg.topic, msg.payload)
        if not event or not self._loop:
            return
        self._loop.call_soon_threadsafe(self._enqueue_event_nowait, event)

    def _enqueue_event_nowait(self, event: CanonicalEnvelope) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"{self.name} MQTT event queue is full, dropping message")

    async def _heartbeat_loop(self) -> None:
        interval = max(5, self.config.heartbeat_interval_seconds)
        while self._running:
            await asyncio.sleep(interval)
            if not self._connected or self._mqtt_client is None:
                continue
            if not self.config.heartbeat_topic:
                continue
            heartbeat = {
                "source": "opencane-hardware",
                "ts": int(time.time() * 1000),
                "connected": True,
            }
            self._mqtt_client.publish(
                self.config.heartbeat_topic,
                payload=json.dumps(heartbeat),
                qos=0,
            )

    def _parse_incoming_message(self, topic: str, payload: bytes) -> CanonicalEnvelope | None:
        device_id = self._extract_device_id_from_topic(topic) or ""

        if self._topic_matches(self.config.up_control_topic, topic):
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception:
                data = {
                    "type": DeviceEventType.ERROR,
                    "device_id": device_id,
                    "payload": {"error": "invalid control payload"},
                }
            device_hint = device_id or str(data.get("device_id") or data.get("deviceId") or "").strip()
            default_session_id = None
            if device_hint:
                default_session_id = self._session_by_device.get(device_hint, f"{device_hint}-default")
            try:
                env = CanonicalEnvelope.from_dict(
                    data,
                    default_device_id=device_hint,
                    default_session_id=default_session_id,
                )
            except ValueError:
                return None
            if env.session_id:
                self._session_by_device[env.device_id] = env.session_id
            if env.type == DeviceEventType.HELLO:
                if self.config.replay_enabled:
                    last_recv_seq = self._extract_last_recv_seq(env.payload)
                    if last_recv_seq is not None:
                        self._replay_control_window(env.device_id, last_recv_seq)
                self._flush_pending_control(env.device_id)
            return env

        if self._topic_matches(self.config.up_audio_topic, topic):
            if not device_id:
                return None
            session_id = self._session_by_device.get(device_id, f"{device_id}-default")
            try:
                return self._parse_audio_packet(payload, device_id=device_id, session_id=session_id)
            except Exception:
                return make_event(
                    DeviceEventType.ERROR,
                    device_id=device_id,
                    session_id=session_id,
                    payload={"error": "invalid audio packet"},
                )
        return None

    def _extract_device_id_from_topic(self, topic: str) -> str | None:
        for pattern in [self.config.up_control_topic, self.config.up_audio_topic]:
            value = self._extract_device_id_by_pattern(pattern, topic)
            if value:
                return value
        parts = [x for x in topic.split("/") if x]
        if len(parts) >= 2 and parts[0].lower() == "device":
            return parts[1]
        return None

    @staticmethod
    def _extract_device_id_by_pattern(pattern: str, topic: str) -> str | None:
        if not EC600MQTTAdapter._topic_matches(pattern, topic):
            return None
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        for i, token in enumerate(pattern_parts):
            if token == "+" and i < len(topic_parts):
                return topic_parts[i]
        return None

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")

        for i, token in enumerate(pattern_parts):
            if token == "#":
                return i == len(pattern_parts) - 1
            if i >= len(topic_parts):
                return False
            if token == "+":
                continue
            if token != topic_parts[i]:
                return False
        return len(topic_parts) == len(pattern_parts)

    def _parse_audio_packet(
        self,
        packet: bytes,
        *,
        device_id: str,
        session_id: str,
    ) -> CanonicalEnvelope:
        if len(packet) < 16:
            raise ValueError("audio packet too short")
        magic = packet[0]
        if magic != self.packet_magic:
            raise ValueError(f"invalid packet magic: {magic}")
        seq = int.from_bytes(packet[4:8], "big")
        ts = int.from_bytes(packet[8:12], "big")
        payload_len = int.from_bytes(packet[12:16], "big")
        if payload_len > len(packet) - 16:
            raise ValueError("audio packet payload length mismatch")
        audio = packet[16 : 16 + payload_len] if payload_len > 0 else packet[16:]
        return make_event(
            DeviceEventType.AUDIO_CHUNK,
            device_id=device_id,
            session_id=session_id,
            seq=seq,
            payload={
                "audio_b64": base64.b64encode(audio).decode("ascii"),
                "encoding": "opus",
                "timestamp": ts,
            },
        )

    def _build_audio_packet(self, audio: bytes, *, seq: int, timestamp: int) -> bytes:
        header = bytearray(16)
        header[0] = self.packet_magic
        header[1] = 1  # protocol version
        header[4:8] = (int(seq) & 0xFFFFFFFF).to_bytes(4, "big")
        header[8:12] = (int(timestamp) & 0xFFFFFFFF).to_bytes(4, "big")
        header[12:16] = (len(audio) & 0xFFFFFFFF).to_bytes(4, "big")
        return bytes(header) + audio

    @staticmethod
    def _render_topic(template: str, device_id: str) -> str:
        return template.replace("{device_id}", device_id)

    @staticmethod
    def _extract_last_recv_seq(payload: dict[str, Any]) -> int | None:
        for key in ("last_recv_seq", "lastRecvSeq"):
            value = payload.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        resume = payload.get("resume")
        if isinstance(resume, dict):
            for key in ("last_recv_seq", "lastRecvSeq"):
                value = resume.get(key)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _buffer_pending_control(
        self,
        device_id: str,
        seq: int,
        topic: str,
        payload: str,
        qos: int,
    ) -> None:
        self._pending_control_by_device[device_id].append((int(seq), topic, payload, int(qos)))

    def _remember_control_window(
        self,
        device_id: str,
        seq: int,
        topic: str,
        payload: str,
        qos: int,
    ) -> None:
        self._control_window_by_device[device_id].append((int(seq), topic, payload, int(qos)))

    def _flush_pending_control(self, device_id: str) -> None:
        if not self._connected or self._mqtt_client is None:
            return
        pending = self._pending_control_by_device.get(device_id)
        if not pending:
            return
        while pending:
            seq, topic, payload, qos = pending.popleft()
            result = self._mqtt_client.publish(topic, payload=payload, qos=qos)
            if result.rc != 0:
                logger.warning(f"MQTT pending control flush failed rc={result.rc} topic={topic}")
                pending.appendleft((seq, topic, payload, qos))
                break
            self._remember_control_window(device_id, seq, topic, payload, qos)
        if not pending:
            self._pending_control_by_device.pop(device_id, None)

    def _replay_control_window(self, device_id: str, last_recv_seq: int) -> None:
        if not self._connected or self._mqtt_client is None:
            return
        window = self._control_window_by_device.get(device_id)
        if not window:
            return
        replayed = 0
        for seq, topic, payload, qos in window:
            if seq <= last_recv_seq:
                continue
            result = self._mqtt_client.publish(topic, payload=payload, qos=qos)
            if result.rc != 0:
                logger.warning(f"MQTT replay failed rc={result.rc} topic={topic}")
                break
            replayed += 1
        if replayed:
            logger.info(
                f"{self.name} replayed {replayed} control commands for {device_id} from last_recv_seq={last_recv_seq}"
            )

    async def inject_event(self, event: CanonicalEnvelope | dict[str, Any]) -> CanonicalEnvelope:
        """Inject canonical event into queue (for tests/debug control API)."""
        canonical = event if isinstance(event, CanonicalEnvelope) else CanonicalEnvelope.from_dict(event)
        await self._queue.put(canonical)
        return canonical

    async def ingest_audio_packet(
        self,
        packet: bytes,
        *,
        device_id: str,
        session_id: str,
    ) -> CanonicalEnvelope:
        """Parse 16-byte framed audio packet and enqueue canonical audio event."""
        envelope = self._parse_audio_packet(packet, device_id=device_id, session_id=session_id)
        await self.inject_event(envelope)
        return envelope

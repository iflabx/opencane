"""Generic MQTT adapter with profile-based field mapping."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Mapping

from loguru import logger

from opencane.config.schema import HardwareMQTTConfig
from opencane.hardware.adapter.device_profiles import (
    GenericMQTTDeviceProfile,
    resolve_generic_mqtt_profile,
)
from opencane.hardware.adapter.ec600_adapter import EC600MQTTAdapter
from opencane.hardware.protocol import (
    CanonicalEnvelope,
    DeviceCommandType,
    DeviceEventType,
    make_event,
)


def _normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


class GenericMQTTAdapter(EC600MQTTAdapter):
    """Profile-driven adapter that maps heterogeneous MQTT payloads to canonical envelopes."""

    name = "generic_mqtt"
    transport = "mqtt"

    def __init__(
        self,
        config: HardwareMQTTConfig,
        *,
        profile: GenericMQTTDeviceProfile | None = None,
        profile_name: str | None = None,
        packet_magic: int = 0xA1,
        audio_up_mode: str | None = None,
        event_type_aliases: Mapping[str, str] | None = None,
        payload_aliases: Mapping[str, str] | None = None,
    ) -> None:
        resolved_profile = profile or resolve_generic_mqtt_profile(profile_name)
        super().__init__(config=config, packet_magic=packet_magic)
        self.profile = resolved_profile
        self.profile_name = resolved_profile.name
        self.audio_up_mode = str(audio_up_mode or resolved_profile.audio_up_mode).strip().lower()

        merged_event_aliases = dict(resolved_profile.event_type_aliases)
        if isinstance(event_type_aliases, Mapping):
            merged_event_aliases.update({str(k): str(v) for k, v in event_type_aliases.items()})
        self._event_type_aliases = {
            _normalize_key(alias): str(target).strip().lower()
            for alias, target in merged_event_aliases.items()
            if str(alias).strip() and str(target).strip()
        }

        merged_payload_aliases = dict(resolved_profile.payload_aliases)
        if isinstance(payload_aliases, Mapping):
            merged_payload_aliases.update({str(k): str(v) for k, v in payload_aliases.items()})
        self._payload_aliases = {
            _normalize_key(alias): str(target).strip()
            for alias, target in merged_payload_aliases.items()
            if str(alias).strip() and str(target).strip()
        }

        self._control_field_aliases = {
            str(field): tuple(str(name) for name in aliases)
            for field, aliases in resolved_profile.control_field_aliases.items()
        }
        reserved = set()
        for aliases in self._control_field_aliases.values():
            reserved.update(_normalize_key(item) for item in aliases)
        self._reserved_control_keys = reserved

        self._json_audio_b64_keys = tuple(str(k) for k in resolved_profile.json_audio_b64_keys)
        self._json_audio_encoding_keys = tuple(str(k) for k in resolved_profile.json_audio_encoding_keys)
        self._json_audio_seq_keys = tuple(str(k) for k in resolved_profile.json_audio_seq_keys)
        self._json_audio_ts_keys = tuple(str(k) for k in resolved_profile.json_audio_ts_keys)
        self._downlink_type_key = str(resolved_profile.downlink_type_key or "type")
        self._downlink_payload_key = str(resolved_profile.downlink_payload_key or "payload")
        self._command_type_aliases = {
            _normalize_key(alias): str(target).strip()
            for alias, target in resolved_profile.command_type_aliases.items()
            if str(alias).strip() and str(target).strip()
        }

    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        if self._mqtt_client is None:
            raise RuntimeError("MQTT client is not initialized")

        topic = self._render_topic(self.config.down_control_topic_template, cmd.device_id)
        payload: str | bytes = self._serialize_control_payload(cmd)
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
                payload = self._build_audio_packet(audio, seq=cmd.seq, timestamp=cmd.ts)

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

    def _parse_incoming_message(self, topic: str, payload: bytes) -> CanonicalEnvelope | None:
        device_from_topic = self._extract_device_id_from_topic(topic) or ""

        if self._topic_matches(self.config.up_control_topic, topic):
            try:
                raw_data = json.loads(payload.decode("utf-8"))
            except Exception:
                return make_event(
                    DeviceEventType.ERROR,
                    device_id=device_from_topic or "unknown",
                    session_id=self._session_by_device.get(
                        device_from_topic,
                        f"{(device_from_topic or 'unknown')}-default",
                    ),
                    payload={"error": "invalid control payload"},
                )

            if not isinstance(raw_data, dict):
                raw_data = {"type": "error", "payload": {"error": "invalid control payload type"}}

            normalized = self._normalize_control_data(raw_data, device_from_topic=device_from_topic)
            device_hint = str(normalized.get("device_id") or device_from_topic or "").strip()
            default_session_id = None
            if device_hint:
                default_session_id = self._session_by_device.get(device_hint, f"{device_hint}-default")
            try:
                env = CanonicalEnvelope.from_dict(
                    normalized,
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
            if not device_from_topic:
                return None
            session_id = self._session_by_device.get(device_from_topic, f"{device_from_topic}-default")
            try:
                if self.audio_up_mode == "json_b64":
                    return self._parse_audio_json_payload(
                        payload,
                        device_id=device_from_topic,
                        session_id=session_id,
                    )
                return self._parse_audio_packet(payload, device_id=device_from_topic, session_id=session_id)
            except Exception:
                return make_event(
                    DeviceEventType.ERROR,
                    device_id=device_from_topic,
                    session_id=session_id,
                    payload={"error": "invalid audio packet"},
                )

        return None

    def _serialize_control_payload(self, cmd: CanonicalEnvelope) -> str:
        data = cmd.to_dict()
        cmd_type = str(data.get("type") or "")
        mapped_type = self._command_type_aliases.get(_normalize_key(cmd_type), cmd_type)
        data["type"] = mapped_type

        if self._downlink_payload_key != "payload":
            data[self._downlink_payload_key] = data.pop("payload", {})
        if self._downlink_type_key != "type":
            data[self._downlink_type_key] = data.pop("type", "")
        return json.dumps(data, ensure_ascii=False)

    def _normalize_control_data(self, data: dict[str, Any], *, device_from_topic: str) -> dict[str, Any]:
        event_type = self._normalize_event_type(
            self._extract_first(data, self._control_field_aliases.get("type", ("type",)))
        )
        device_id = str(
            self._extract_first(data, self._control_field_aliases.get("device_id", ("device_id",)))
            or device_from_topic
            or ""
        ).strip()
        session_id = str(
            self._extract_first(data, self._control_field_aliases.get("session_id", ("session_id",))) or ""
        ).strip()
        seq = self._as_int(self._extract_first(data, self._control_field_aliases.get("seq", ("seq",))), 0)
        ts = self._as_int(self._extract_first(data, self._control_field_aliases.get("ts", ("ts",))), 0)
        msg_id = self._extract_first(data, self._control_field_aliases.get("msg_id", ("msg_id",)))
        version = self._extract_first(data, self._control_field_aliases.get("version", ("version", "v")))

        payload_raw = self._extract_first(data, self._control_field_aliases.get("payload", ("payload",)))
        if isinstance(payload_raw, dict):
            payload: dict[str, Any] = dict(payload_raw)
        elif payload_raw is None:
            payload = {
                str(key): value
                for key, value in data.items()
                if _normalize_key(str(key)) not in self._reserved_control_keys
            }
        else:
            payload = {"value": payload_raw}
        payload = self._apply_payload_aliases(payload)

        normalized: dict[str, Any] = {
            "device_id": device_id,
            "session_id": session_id,
            "seq": max(0, seq),
            "type": event_type,
            "payload": payload,
        }
        if ts > 0:
            normalized["ts"] = ts
        if msg_id is not None:
            normalized["msg_id"] = str(msg_id)
        if version is not None:
            normalized["version"] = str(version)
        return normalized

    def _parse_audio_json_payload(
        self,
        payload: bytes,
        *,
        device_id: str,
        session_id: str,
    ) -> CanonicalEnvelope:
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("audio json payload must be object")

        nested = self._extract_first(data, self._control_field_aliases.get("payload", ("payload",)))
        source = nested if isinstance(nested, dict) else data
        b64_value = self._extract_first(source, self._json_audio_b64_keys)
        if b64_value is None and source is not data:
            b64_value = self._extract_first(data, self._json_audio_b64_keys)
        if b64_value is None:
            raise ValueError("audio json payload missing base64 field")

        seq = self._as_int(self._extract_first(source, self._json_audio_seq_keys), 0)
        if seq <= 0:
            seq = self._as_int(self._extract_first(data, self._json_audio_seq_keys), 0)
        ts = self._as_int(self._extract_first(source, self._json_audio_ts_keys), 0)
        if ts <= 0:
            ts = self._as_int(self._extract_first(data, self._json_audio_ts_keys), 0)
        if ts < 0:
            ts = 0

        encoding = str(self._extract_first(source, self._json_audio_encoding_keys) or "opus").strip() or "opus"
        payload_data = {
            "audio_b64": str(b64_value),
            "encoding": encoding,
            "timestamp": ts,
        }
        resolved_device_id = str(
            self._extract_first(source, self._control_field_aliases.get("device_id", ("device_id",)))
            or self._extract_first(data, self._control_field_aliases.get("device_id", ("device_id",)))
            or device_id
        ).strip() or device_id
        resolved_session_id = str(
            self._extract_first(source, self._control_field_aliases.get("session_id", ("session_id",)))
            or self._extract_first(data, self._control_field_aliases.get("session_id", ("session_id",)))
            or session_id
        ).strip() or session_id
        if resolved_session_id:
            self._session_by_device[resolved_device_id] = resolved_session_id
        return make_event(
            DeviceEventType.AUDIO_CHUNK,
            device_id=resolved_device_id,
            session_id=resolved_session_id,
            seq=max(0, seq),
            payload=payload_data,
        )

    def _normalize_event_type(self, event_type: Any) -> str:
        raw = str(event_type or "").strip().lower()
        if not raw:
            return ""
        normalized = _normalize_key(raw)
        return self._event_type_aliases.get(normalized, raw)

    def _apply_payload_aliases(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return payload
        rewritten = dict(payload)
        existing = {_normalize_key(k): k for k in rewritten}
        for key, value in list(rewritten.items()):
            target = self._payload_aliases.get(_normalize_key(key))
            if not target:
                continue
            if target in rewritten:
                continue
            rewritten[target] = value
            existing[_normalize_key(target)] = target
        return rewritten

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _extract_first(data: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
        if not isinstance(data, Mapping):
            return None
        key_index = {_normalize_key(str(key)): key for key in data}
        for name in keys:
            direct = data.get(name)
            if direct is not None:
                return direct
            matched_key = key_index.get(_normalize_key(name))
            if matched_key is not None:
                value = data.get(matched_key)
                if value is not None:
                    return value
        return None

"""Built-in device profiles for generic MQTT southbound adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from nanobot.config.schema import HardwareMQTTConfig


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


def _normalize_audio_mode(mode: str | None) -> str:
    text = _normalize_name(str(mode or ""))
    if text in {"json", "json_b64", "base64", "jsonbase64"}:
        return "json_b64"
    return "framed_packet"


_DEFAULT_CONTROL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "type": ("type", "event", "evt", "cmd"),
    "device_id": ("device_id", "deviceId", "dev_id", "devId", "imei"),
    "session_id": ("session_id", "sessionId", "sid"),
    "seq": ("seq", "sequence", "msg_seq", "msgSeq", "index"),
    "ts": ("ts", "timestamp", "time", "t"),
    "payload": ("payload", "data", "body", "params"),
    "msg_id": ("msg_id", "msgId", "message_id", "messageId", "id"),
    "version": ("version", "v"),
}

_DEFAULT_EVENT_TYPE_ALIASES: dict[str, str] = {
    "boot": "hello",
    "startup": "hello",
    "hb": "heartbeat",
    "ping": "heartbeat",
    "mic_start": "listen_start",
    "start": "listen_start",
    "mic_stop": "listen_stop",
    "stop": "listen_stop",
    "audio": "audio_chunk",
    "chunk": "audio_chunk",
    "img": "image_ready",
    "image": "image_ready",
    "sensor": "telemetry",
    "metrics": "telemetry",
}

_DEFAULT_PAYLOAD_ALIASES: dict[str, str] = {
    "lastrecvseq": "last_recv_seq",
    "chunkindex": "chunk_index",
    "audiobase64": "audio_b64",
    "imageurl": "image_url",
}


@dataclass(frozen=True)
class GenericMQTTDeviceProfile:
    """Profile describing transport defaults and lightweight payload mapping."""

    name: str
    modem_model: str
    packet_magic: int = 0xA1
    audio_up_mode: str = "framed_packet"  # framed_packet | json_b64
    mqtt_defaults: dict[str, Any] = field(default_factory=dict)
    control_field_aliases: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(_DEFAULT_CONTROL_FIELD_ALIASES)
    )
    event_type_aliases: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_EVENT_TYPE_ALIASES))
    payload_aliases: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_PAYLOAD_ALIASES))
    json_audio_b64_keys: tuple[str, ...] = ("audio_b64", "audioBase64", "audio", "data")
    json_audio_encoding_keys: tuple[str, ...] = ("encoding", "codec", "format")
    json_audio_seq_keys: tuple[str, ...] = ("seq", "chunk_index", "chunkIndex", "index")
    json_audio_ts_keys: tuple[str, ...] = ("ts", "timestamp", "time")
    downlink_type_key: str = "type"
    downlink_payload_key: str = "payload"
    command_type_aliases: dict[str, str] = field(default_factory=dict)


def _profile(
    *,
    name: str,
    modem_model: str,
    keepalive_seconds: int,
    reconnect_min_seconds: int,
    reconnect_max_seconds: int,
    qos_control: int = 1,
    qos_audio: int = 0,
    packet_magic: int = 0xA1,
    audio_up_mode: str = "framed_packet",
) -> GenericMQTTDeviceProfile:
    return GenericMQTTDeviceProfile(
        name=name,
        modem_model=modem_model,
        packet_magic=packet_magic,
        audio_up_mode=audio_up_mode,
        mqtt_defaults={
            "qos_control": qos_control,
            "qos_audio": qos_audio,
            "keepalive_seconds": keepalive_seconds,
            "reconnect_min_seconds": reconnect_min_seconds,
            "reconnect_max_seconds": reconnect_max_seconds,
            "up_control_topic": "device/+/up/control",
            "up_audio_topic": "device/+/up/audio",
            "down_control_topic_template": "device/{device_id}/down/control",
            "down_audio_topic_template": "device/{device_id}/down/audio",
            "heartbeat_interval_seconds": 30,
            "replay_enabled": True,
            "control_replay_window": 100,
            "offline_control_buffer": 120,
        },
    )


_BUILTIN_GENERIC_MQTT_PROFILES: dict[str, GenericMQTTDeviceProfile] = {
    "generic_v1": _profile(
        name="generic_v1",
        modem_model="generic-cellular",
        keepalive_seconds=45,
        reconnect_min_seconds=2,
        reconnect_max_seconds=60,
    ),
    "ec600mcnle_v1": _profile(
        name="ec600mcnle_v1",
        modem_model="EC600MCNLE",
        keepalive_seconds=45,
        reconnect_min_seconds=2,
        reconnect_max_seconds=60,
    ),
    "a7670c_v1": _profile(
        name="a7670c_v1",
        modem_model="A7670C",
        keepalive_seconds=50,
        reconnect_min_seconds=2,
        reconnect_max_seconds=75,
    ),
    "sim7600g_h_v1": _profile(
        name="sim7600g_h_v1",
        modem_model="SIM7600G-H",
        keepalive_seconds=60,
        reconnect_min_seconds=2,
        reconnect_max_seconds=90,
    ),
    "ec800m_v1": _profile(
        name="ec800m_v1",
        modem_model="EC800M",
        keepalive_seconds=45,
        reconnect_min_seconds=2,
        reconnect_max_seconds=60,
    ),
    "ml307r_dl_v1": _profile(
        name="ml307r_dl_v1",
        modem_model="ML307R-DL",
        keepalive_seconds=45,
        reconnect_min_seconds=2,
        reconnect_max_seconds=60,
    ),
}

_PROFILE_ALIASES: dict[str, str] = {
    "generic": "generic_v1",
    "genericmqtt": "generic_v1",
    "ec600": "ec600mcnle_v1",
    "ec600mcnle": "ec600mcnle_v1",
    "a7670": "a7670c_v1",
    "a7670c": "a7670c_v1",
    "sim7600": "sim7600g_h_v1",
    "sim7600gh": "sim7600g_h_v1",
    "sim7600g_h": "sim7600g_h_v1",
    "ec800": "ec800m_v1",
    "ec800m": "ec800m_v1",
    "ml307": "ml307r_dl_v1",
    "ml307rdl": "ml307r_dl_v1",
    "ml307r_dl": "ml307r_dl_v1",
}


def resolve_generic_mqtt_profile(profile_name: str | None) -> GenericMQTTDeviceProfile:
    """Resolve profile by canonical name or aliases."""
    if not profile_name:
        return _BUILTIN_GENERIC_MQTT_PROFILES["generic_v1"]
    normalized = _normalize_name(profile_name)
    direct = _BUILTIN_GENERIC_MQTT_PROFILES.get(normalized)
    if direct:
        return direct
    alias = _PROFILE_ALIASES.get(_normalize_key(profile_name))
    if alias:
        return _BUILTIN_GENERIC_MQTT_PROFILES[alias]
    supported = ", ".join(sorted(_BUILTIN_GENERIC_MQTT_PROFILES))
    raise ValueError(
        f"Unsupported hardware.device_profile={profile_name!r}. Supported profiles: {supported}"
    )


def list_generic_mqtt_profiles() -> list[str]:
    """List built-in generic MQTT profile names."""
    return sorted(_BUILTIN_GENERIC_MQTT_PROFILES)


def _get_mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    if not mapping:
        return None
    normalized_index = {_normalize_key(k): v for k, v in mapping.items()}
    for key in keys:
        value = normalized_index.get(_normalize_key(key))
        if value is not None:
            return value
    return None


_MQTT_FIELDS = set(HardwareMQTTConfig.model_fields)
_MQTT_FIELDS_BY_NORMALIZED = {_normalize_key(name): name for name in _MQTT_FIELDS}


def _apply_mqtt_overrides(config: HardwareMQTTConfig, overrides: Mapping[str, Any] | None) -> None:
    if not isinstance(overrides, Mapping):
        return
    for raw_key, raw_value in overrides.items():
        target = _MQTT_FIELDS_BY_NORMALIZED.get(_normalize_key(str(raw_key)))
        if not target:
            continue
        setattr(config, target, raw_value)


def build_generic_mqtt_runtime(
    base_config: HardwareMQTTConfig,
    *,
    profile_name: str | None,
    profile_overrides: Mapping[str, Any] | None,
    fallback_packet_magic: int = 0xA1,
) -> tuple[HardwareMQTTConfig, GenericMQTTDeviceProfile, int, str]:
    """Build resolved MQTT config + runtime options for generic adapter."""
    profile = resolve_generic_mqtt_profile(profile_name)
    mqtt_config = base_config.model_copy(deep=True)
    _apply_mqtt_overrides(mqtt_config, profile.mqtt_defaults)

    overrides = profile_overrides if isinstance(profile_overrides, Mapping) else {}
    _apply_mqtt_overrides(mqtt_config, _get_mapping_value(overrides, "mqtt"))

    raw_packet_magic = _get_mapping_value(overrides, "packet_magic", "packetMagic")
    try:
        packet_magic = int(raw_packet_magic) if raw_packet_magic is not None else int(profile.packet_magic)
    except (TypeError, ValueError):
        packet_magic = int(profile.packet_magic)
    if packet_magic < 0:
        packet_magic = int(profile.packet_magic or fallback_packet_magic)
    packet_magic = packet_magic & 0xFF
    if packet_magic == 0:
        packet_magic = int(profile.packet_magic or fallback_packet_magic) & 0xFF

    raw_audio_mode = _get_mapping_value(overrides, "audio_up_mode", "audioUpMode")
    audio_mode = _normalize_audio_mode(str(raw_audio_mode or profile.audio_up_mode))
    return mqtt_config, profile, packet_magic, audio_mode

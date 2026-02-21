import json

import pytest

from opencane.config.schema import HardwareMQTTConfig
from opencane.hardware.adapter.device_profiles import (
    GenericMQTTDeviceProfile,
    resolve_generic_mqtt_profile,
)
from opencane.hardware.adapter.generic_mqtt_adapter import GenericMQTTAdapter
from opencane.hardware.protocol import DeviceCommandType, DeviceEventType, make_command


class _FakePublishResult:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc


class _FakeMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str | bytes, int]] = []

    def publish(self, topic: str, payload, qos: int):  # type: ignore[no-untyped-def]
        self.published.append((topic, payload, qos))
        return _FakePublishResult(rc=0)


def _make_adapter(**kwargs) -> GenericMQTTAdapter:
    config = HardwareMQTTConfig(**kwargs)
    profile = resolve_generic_mqtt_profile("ml307r_dl_v1")
    return GenericMQTTAdapter(config=config, profile=profile, packet_magic=0xA1)


def test_parse_control_payload_with_alias_fields() -> None:
    adapter = _make_adapter(up_control_topic="modem/+/uplink/control", up_audio_topic="modem/+/uplink/audio")
    raw = {
        "event": "hb",
        "devId": "dev-alias",
        "sid": "sess-alias",
        "sequence": 6,
        "data": {"lastRecvSeq": 4, "rssi": -72},
    }
    env = adapter._parse_incoming_message(
        "modem/dev-alias/uplink/control",
        json.dumps(raw).encode("utf-8"),
    )
    assert env is not None
    assert env.type == DeviceEventType.HEARTBEAT
    assert env.device_id == "dev-alias"
    assert env.session_id == "sess-alias"
    assert env.seq == 6
    assert env.payload["last_recv_seq"] == 4


def test_parse_audio_json_mode() -> None:
    adapter = _make_adapter(up_control_topic="modem/+/ctl", up_audio_topic="modem/+/audio")
    adapter.audio_up_mode = "json_b64"
    raw = {
        "devId": "dev-a",
        "sid": "sess-a",
        "seq": 11,
        "timestamp": 12345,
        "audioBase64": "aGVsbG8=",
        "codec": "opus",
    }
    env = adapter._parse_incoming_message("modem/dev-a/audio", json.dumps(raw).encode("utf-8"))
    assert env is not None
    assert env.type == DeviceEventType.AUDIO_CHUNK
    assert env.device_id == "dev-a"
    assert env.session_id == "sess-a"
    assert env.seq == 11
    assert env.payload["audio_b64"] == "aGVsbG8="
    assert env.payload["encoding"] == "opus"


@pytest.mark.asyncio
async def test_send_command_supports_downlink_type_alias() -> None:
    profile = GenericMQTTDeviceProfile(
        name="custom_v1",
        modem_model="custom",
        command_type_aliases={"tts_stop": "stop_tts"},
        downlink_type_key="cmd",
        downlink_payload_key="data",
    )
    adapter = GenericMQTTAdapter(config=HardwareMQTTConfig(), profile=profile, packet_magic=0xA1)
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    cmd = make_command(
        DeviceCommandType.TTS_STOP,
        device_id="dev-downlink",
        session_id="sess-1",
        seq=5,
        payload={"aborted": False},
    )
    await adapter.send_command(cmd)

    assert len(fake.published) == 1
    _, payload, _ = fake.published[0]
    assert isinstance(payload, str)
    parsed = json.loads(payload)
    assert parsed["cmd"] == "stop_tts"
    assert parsed["data"] == {"aborted": False}

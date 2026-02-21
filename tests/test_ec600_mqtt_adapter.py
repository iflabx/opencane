import base64
import json

import pytest

from opencane.config.schema import HardwareMQTTConfig
from opencane.hardware.adapter.ec600_adapter import EC600MQTTAdapter
from opencane.hardware.protocol import DeviceCommandType, DeviceEventType, make_command


def make_adapter(**kwargs):
    config = HardwareMQTTConfig(**kwargs)
    return EC600MQTTAdapter(config=config, packet_magic=0xA1)


class _FakePublishResult:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc


class _FakeMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str | bytes, int]] = []

    def publish(self, topic: str, payload, qos: int):  # type: ignore[no-untyped-def]
        self.published.append((topic, payload, qos))
        return _FakePublishResult(rc=0)


def test_topic_matches_exact_plus_and_hash() -> None:
    assert EC600MQTTAdapter._topic_matches("device/+/up/control", "device/d1/up/control")
    assert not EC600MQTTAdapter._topic_matches("device/+/up/control", "device/d1/up/audio")
    assert EC600MQTTAdapter._topic_matches("device/#", "device/d1/up/audio")
    assert not EC600MQTTAdapter._topic_matches("device/#/bad", "device/d1/up/audio")


def test_extract_device_id_from_topic_uses_pattern() -> None:
    adapter = make_adapter(up_control_topic="hw/+/evt", up_audio_topic="hw/+/audio")
    assert adapter._extract_device_id_from_topic("hw/dev-99/evt") == "dev-99"
    assert adapter._extract_device_id_from_topic("hw/dev-77/audio") == "dev-77"


def test_parse_control_message_success_and_session_tracking() -> None:
    adapter = make_adapter()
    payload = {
        "type": "hello",
        "device_id": "dev-a",
        "session_id": "sess-a",
        "seq": 1,
        "payload": {"capabilities": {"voice": True}},
    }
    env = adapter._parse_incoming_message(
        "device/dev-a/up/control",
        json.dumps(payload).encode("utf-8"),
    )
    assert env is not None
    assert env.type == DeviceEventType.HELLO
    assert env.device_id == "dev-a"
    assert adapter._session_by_device["dev-a"] == "sess-a"


def test_parse_control_message_without_session_reuses_tracked_session() -> None:
    adapter = make_adapter()
    hello = {
        "type": "hello",
        "device_id": "dev-a",
        "session_id": "sess-a",
        "seq": 1,
    }
    adapter._parse_incoming_message(
        "device/dev-a/up/control",
        json.dumps(hello).encode("utf-8"),
    )

    heartbeat = {
        "type": "heartbeat",
        "device_id": "dev-a",
        "seq": 2,
    }
    env = adapter._parse_incoming_message(
        "device/dev-a/up/control",
        json.dumps(heartbeat).encode("utf-8"),
    )
    assert env is not None
    assert env.type == DeviceEventType.HEARTBEAT
    assert env.session_id == "sess-a"
    assert adapter._session_by_device["dev-a"] == "sess-a"


def test_parse_control_message_without_session_uses_stable_default_session() -> None:
    adapter = make_adapter()
    payload = {"type": "heartbeat", "seq": 3}
    env = adapter._parse_incoming_message(
        "device/dev-z/up/control",
        json.dumps(payload).encode("utf-8"),
    )
    assert env is not None
    assert env.device_id == "dev-z"
    assert env.session_id == "dev-z-default"
    assert adapter._session_by_device["dev-z"] == "dev-z-default"


def test_parse_control_message_invalid_json_returns_error_event() -> None:
    adapter = make_adapter()
    env = adapter._parse_incoming_message("device/dev-e/up/control", b"{bad")
    assert env is not None
    assert env.type == DeviceEventType.ERROR
    assert env.device_id == "dev-e"
    assert env.payload.get("error") == "invalid control payload"


def test_parse_audio_message_success_with_default_session() -> None:
    adapter = make_adapter()
    raw_audio = b"hello-audio"
    packet = adapter._build_audio_packet(raw_audio, seq=7, timestamp=1234)
    env = adapter._parse_incoming_message("device/dev-a/up/audio", packet)
    assert env is not None
    assert env.type == DeviceEventType.AUDIO_CHUNK
    assert env.device_id == "dev-a"
    assert env.session_id == "dev-a-default"
    assert env.seq == 7
    assert base64.b64decode(env.payload["audio_b64"]) == raw_audio


def test_parse_audio_message_invalid_packet_returns_error_event() -> None:
    adapter = make_adapter()
    env = adapter._parse_incoming_message("device/dev-x/up/audio", b"short")
    assert env is not None
    assert env.type == DeviceEventType.ERROR
    assert env.payload.get("error") == "invalid audio packet"


def test_audio_packet_round_trip_with_timestamp_wrap() -> None:
    adapter = make_adapter()
    raw_audio = b"abc123"
    packet = adapter._build_audio_packet(raw_audio, seq=9, timestamp=1 << 40)
    env = adapter._parse_audio_packet(packet, device_id="dev-r", session_id="sess-r")
    assert env.type == DeviceEventType.AUDIO_CHUNK
    assert env.seq == 9
    assert env.payload["timestamp"] == 0
    assert base64.b64decode(env.payload["audio_b64"]) == raw_audio


@pytest.mark.asyncio
async def test_control_command_is_buffered_when_disconnected_and_flushed_on_hello() -> None:
    adapter = make_adapter()
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = False

    cmd = make_command(
        DeviceCommandType.TTS_STOP,
        device_id="dev-buffer",
        session_id="sess-1",
        seq=11,
        payload={"aborted": False},
    )
    await adapter.send_command(cmd)
    assert len(adapter._pending_control_by_device["dev-buffer"]) == 1

    adapter._connected = True
    hello = {
        "type": "hello",
        "device_id": "dev-buffer",
        "session_id": "sess-1",
        "payload": {},
    }
    adapter._parse_incoming_message("device/dev-buffer/up/control", json.dumps(hello).encode("utf-8"))
    assert len(fake.published) == 1
    assert fake.published[0][0] == "device/dev-buffer/down/control"
    assert "dev-buffer" not in adapter._pending_control_by_device


def test_replay_control_window_resends_commands_after_last_recv_seq() -> None:
    adapter = make_adapter()
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    adapter._remember_control_window("dev-replay", 1, "device/dev-replay/down/control", '{"seq":1}', 1)
    adapter._remember_control_window("dev-replay", 3, "device/dev-replay/down/control", '{"seq":3}', 1)
    adapter._replay_control_window("dev-replay", last_recv_seq=1)

    assert len(fake.published) == 1
    assert fake.published[0][1] == '{"seq":3}'


def test_replay_control_window_skips_equal_or_older_seq() -> None:
    adapter = make_adapter()
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    adapter._remember_control_window("dev-replay", 1, "device/dev-replay/down/control", '{"seq":1}', 1)
    adapter._remember_control_window("dev-replay", 3, "device/dev-replay/down/control", '{"seq":3}', 1)
    adapter._replay_control_window("dev-replay", last_recv_seq=3)

    assert fake.published == []


def test_replay_control_window_respects_maxlen() -> None:
    adapter = make_adapter(control_replay_window=2)
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    adapter._remember_control_window("dev-cap", 1, "device/dev-cap/down/control", '{"seq":1}', 1)
    adapter._remember_control_window("dev-cap", 2, "device/dev-cap/down/control", '{"seq":2}', 1)
    adapter._remember_control_window("dev-cap", 3, "device/dev-cap/down/control", '{"seq":3}', 1)
    adapter._replay_control_window("dev-cap", last_recv_seq=0)

    assert [payload for _, payload, _ in fake.published] == ['{"seq":2}', '{"seq":3}']


@pytest.mark.asyncio
async def test_offline_control_buffer_respects_maxlen() -> None:
    adapter = make_adapter(offline_control_buffer=2)
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = False

    for seq in [1, 2, 3]:
        cmd = make_command(
            DeviceCommandType.TTS_STOP,
            device_id="dev-pending",
            session_id="sess-1",
            seq=seq,
            payload={"aborted": False},
        )
        await adapter.send_command(cmd)

    pending = list(adapter._pending_control_by_device["dev-pending"])
    assert [item[0] for item in pending] == [2, 3]


@pytest.mark.asyncio
async def test_hello_replays_then_flushes_without_duplicate_pending_republish() -> None:
    adapter = make_adapter()
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    adapter._remember_control_window("dev-rf", 3, "device/dev-rf/down/control", '{"seq":3}', 1)

    adapter._connected = False
    pending_cmd = make_command(
        DeviceCommandType.TTS_STOP,
        device_id="dev-rf",
        session_id="sess-1",
        seq=4,
        payload={"aborted": False},
    )
    await adapter.send_command(pending_cmd)
    assert len(adapter._pending_control_by_device["dev-rf"]) == 1

    adapter._connected = True
    hello = {
        "type": "hello",
        "device_id": "dev-rf",
        "session_id": "sess-1",
        "payload": {"last_recv_seq": 2},
    }
    adapter._parse_incoming_message("device/dev-rf/up/control", json.dumps(hello).encode("utf-8"))

    published_seqs: list[int] = []
    for _, payload, _ in fake.published:
        if isinstance(payload, bytes):
            continue
        parsed = json.loads(payload)
        published_seqs.append(int(parsed["seq"]))

    assert sorted(published_seqs) == [3, 4]


@pytest.mark.asyncio
async def test_hello_flushes_pending_when_replay_disabled() -> None:
    adapter = make_adapter(replay_enabled=False)
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = False

    cmd = make_command(
        DeviceCommandType.TTS_STOP,
        device_id="dev-no-replay",
        session_id="sess-1",
        seq=9,
        payload={"aborted": False},
    )
    await adapter.send_command(cmd)
    assert len(adapter._pending_control_by_device["dev-no-replay"]) == 1

    adapter._connected = True
    hello = {"type": "hello", "device_id": "dev-no-replay", "session_id": "sess-1", "payload": {}}
    adapter._parse_incoming_message(
        "device/dev-no-replay/up/control",
        json.dumps(hello).encode("utf-8"),
    )

    assert len(fake.published) == 1


@pytest.mark.asyncio
async def test_disconnect_reconnect_replays_and_flushes_in_expected_order() -> None:
    adapter = make_adapter()
    fake = _FakeMQTTClient()
    adapter._mqtt_client = fake
    adapter._connected = True

    for seq in [1, 2]:
        cmd = make_command(
            DeviceCommandType.TTS_STOP,
            device_id="dev-recover",
            session_id="sess-1",
            seq=seq,
            payload={"aborted": False},
        )
        await adapter.send_command(cmd)

    adapter._connected = False
    for seq in [3, 4]:
        cmd = make_command(
            DeviceCommandType.TTS_STOP,
            device_id="dev-recover",
            session_id="sess-1",
            seq=seq,
            payload={"aborted": False},
        )
        await adapter.send_command(cmd)

    adapter._connected = True
    hello = {
        "type": "hello",
        "device_id": "dev-recover",
        "session_id": "sess-1",
        "payload": {"last_recv_seq": 1},
    }
    adapter._parse_incoming_message(
        "device/dev-recover/up/control",
        json.dumps(hello).encode("utf-8"),
    )

    seqs: list[int] = []
    for _, payload, _ in fake.published:
        if isinstance(payload, bytes):
            continue
        parsed = json.loads(payload)
        seqs.append(int(parsed["seq"]))

    assert seqs == [1, 2, 2, 3, 4]

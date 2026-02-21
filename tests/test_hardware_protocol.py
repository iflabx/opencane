from opencane.hardware.protocol.envelope import (
    CanonicalEnvelope,
    DeviceCommandType,
    DeviceEventType,
    make_command,
    make_event,
)


def test_canonical_envelope_from_dict_defaults() -> None:
    env = CanonicalEnvelope.from_dict(
        {
            "type": "hello",
            "device_id": "dev-1",
            "payload": {"a": 1},
        }
    )
    assert env.version == "0.1"
    assert env.device_id == "dev-1"
    assert env.type == "hello"
    assert env.session_id


def test_canonical_envelope_from_dict_validation() -> None:
    try:
        CanonicalEnvelope.from_dict({"type": "hello"})
        assert False, "expected ValueError when device_id missing"
    except ValueError as e:
        assert "device_id" in str(e)


def test_make_event_and_command() -> None:
    ev = make_event(
        DeviceEventType.LISTEN_START,
        device_id="d1",
        session_id="s1",
        seq=2,
        payload={"mode": "auto"},
    )
    cmd = make_command(
        DeviceCommandType.TTS_START,
        device_id="d1",
        session_id="s1",
        payload={"text": "hello"},
    )
    assert ev.type == "listen_start"
    assert cmd.type == "tts_start"
    assert ev.seq == 2
    assert cmd.payload["text"] == "hello"


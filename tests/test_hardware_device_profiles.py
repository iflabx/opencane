from nanobot.config.schema import HardwareMQTTConfig
from nanobot.hardware.adapter.device_profiles import (
    build_generic_mqtt_runtime,
    list_generic_mqtt_profiles,
    resolve_generic_mqtt_profile,
)


def test_resolve_generic_profile_aliases() -> None:
    assert resolve_generic_mqtt_profile("EC800M").name == "ec800m_v1"
    assert resolve_generic_mqtt_profile("sim7600g-h").name == "sim7600g_h_v1"
    assert resolve_generic_mqtt_profile("ML307R-DL").name == "ml307r_dl_v1"


def test_list_generic_profiles_includes_latest_modems() -> None:
    names = set(list_generic_mqtt_profiles())
    assert {"ec800m_v1", "ml307r_dl_v1", "a7670c_v1", "sim7600g_h_v1"} <= names


def test_build_runtime_applies_profile_defaults_and_overrides() -> None:
    mqtt, profile, packet_magic, audio_mode = build_generic_mqtt_runtime(
        HardwareMQTTConfig(),
        profile_name="sim7600g_h_v1",
        profile_overrides={
            "mqtt": {
                "keepaliveSeconds": 72,
                "up_control_topic": "modem/+/uplink/control",
            },
            "packetMagic": 177,
            "audioUpMode": "json_b64",
        },
        fallback_packet_magic=0xA1,
    )

    assert profile.name == "sim7600g_h_v1"
    assert mqtt.keepalive_seconds == 72
    assert mqtt.up_control_topic == "modem/+/uplink/control"
    assert packet_magic == 177
    assert audio_mode == "json_b64"


def test_build_runtime_rejects_unknown_profile() -> None:
    try:
        build_generic_mqtt_runtime(
            HardwareMQTTConfig(),
            profile_name="unknown_modem_x",
            profile_overrides={},
            fallback_packet_magic=0xA1,
        )
    except ValueError as exc:
        assert "Unsupported hardware.device_profile" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown profile")

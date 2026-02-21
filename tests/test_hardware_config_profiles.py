from opencane.config.schema import HardwareConfig


def test_cellular_profile_applies_conservative_defaults() -> None:
    cfg = HardwareConfig(
        network_profile="cellular",
        apply_profile_defaults=True,
    )
    cfg.heartbeat_seconds = 20
    cfg.mqtt.keepalive_seconds = 30
    cfg.mqtt.reconnect_min_seconds = 1
    cfg.mqtt.reconnect_max_seconds = 30
    cfg.mqtt.heartbeat_interval_seconds = 20

    cfg.apply_network_profile()

    assert cfg.heartbeat_seconds == 30
    assert cfg.mqtt.keepalive_seconds == 45
    assert cfg.mqtt.reconnect_min_seconds == 2
    assert cfg.mqtt.reconnect_max_seconds == 60
    assert cfg.mqtt.heartbeat_interval_seconds == 30


def test_profile_defaults_can_be_disabled() -> None:
    cfg = HardwareConfig(
        network_profile="cellular",
        apply_profile_defaults=False,
    )
    cfg.heartbeat_seconds = 20
    cfg.mqtt.keepalive_seconds = 30
    cfg.mqtt.reconnect_min_seconds = 1
    cfg.mqtt.reconnect_max_seconds = 30
    cfg.mqtt.heartbeat_interval_seconds = 20

    cfg.apply_network_profile()

    assert cfg.heartbeat_seconds == 20
    assert cfg.mqtt.keepalive_seconds == 30
    assert cfg.mqtt.reconnect_min_seconds == 1
    assert cfg.mqtt.reconnect_max_seconds == 30
    assert cfg.mqtt.heartbeat_interval_seconds == 20

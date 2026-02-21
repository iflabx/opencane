import pytest

from nanobot.api.hardware_server import create_adapter_from_config
from nanobot.config.schema import HardwareConfig
from nanobot.hardware.adapter import EC600MQTTAdapter, GenericMQTTAdapter


def test_create_adapter_from_config_generic_mqtt_profile() -> None:
    cfg = HardwareConfig(adapter="generic_mqtt", device_profile="ec800m")
    cfg.profile_overrides = {"mqtt": {"upControlTopic": "modem/+/up/control"}}
    adapter = create_adapter_from_config(cfg)

    assert isinstance(adapter, GenericMQTTAdapter)
    assert adapter.profile.name == "ec800m_v1"
    assert adapter.config.up_control_topic == "modem/+/up/control"
    assert adapter.config.keepalive_seconds == 45


def test_create_adapter_from_config_ec600_compat() -> None:
    cfg = HardwareConfig(adapter="ec600")
    adapter = create_adapter_from_config(cfg)
    assert isinstance(adapter, EC600MQTTAdapter)


def test_create_adapter_from_config_generic_mqtt_unknown_profile_raises() -> None:
    cfg = HardwareConfig(adapter="generic_mqtt", device_profile="x-unknown")
    with pytest.raises(ValueError):
        create_adapter_from_config(cfg)

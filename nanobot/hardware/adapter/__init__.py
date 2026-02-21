"""Southbound adapters that map raw device protocols to canonical envelopes."""

from nanobot.hardware.adapter.base import GatewayAdapter
from nanobot.hardware.adapter.device_profiles import (
    GenericMQTTDeviceProfile,
    build_generic_mqtt_runtime,
    list_generic_mqtt_profiles,
    resolve_generic_mqtt_profile,
)
from nanobot.hardware.adapter.ec600_adapter import EC600Adapter, EC600MQTTAdapter
from nanobot.hardware.adapter.generic_mqtt_adapter import GenericMQTTAdapter
from nanobot.hardware.adapter.mock_adapter import MockAdapter
from nanobot.hardware.adapter.websocket_adapter import WebSocketAdapter

__all__ = [
    "GatewayAdapter",
    "MockAdapter",
    "EC600Adapter",
    "EC600MQTTAdapter",
    "GenericMQTTAdapter",
    "GenericMQTTDeviceProfile",
    "resolve_generic_mqtt_profile",
    "list_generic_mqtt_profiles",
    "build_generic_mqtt_runtime",
    "WebSocketAdapter",
]

"""Canonical protocol envelopes used by hardware adapters and runtime."""

from opencane.hardware.protocol.envelope import (
    CanonicalEnvelope,
    DeviceCommandType,
    DeviceEventType,
    make_command,
    make_event,
)

__all__ = [
    "CanonicalEnvelope",
    "DeviceCommandType",
    "DeviceEventType",
    "make_command",
    "make_event",
]


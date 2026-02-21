"""Telemetry normalization utilities for hardware runtime."""

from __future__ import annotations

import time
from typing import Any

TELEMETRY_SCHEMA_VERSION = "opencane.telemetry.v1"


def normalize_telemetry_payload(
    payload: dict[str, Any] | None,
    *,
    ts_ms: int | None = None,
) -> dict[str, Any]:
    """Normalize heterogeneous telemetry payloads into one stable internal schema."""
    data = payload if isinstance(payload, dict) else {}
    output: dict[str, Any] = {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "ts_ms": int(ts_ms or _now_ms()),
    }

    battery = _extract_battery(data)
    if battery:
        output["battery"] = battery

    network = _extract_network(data)
    if network:
        output["network"] = network

    location = _extract_location(data)
    if location:
        output["location"] = location

    motion = _extract_motion(data)
    if motion:
        output["motion"] = motion

    imu = _extract_imu(data)
    if imu:
        output["imu"] = imu

    system = _extract_system(data)
    if system:
        output["system"] = system

    if len(output) <= 2:
        return {}
    return output


def _extract_battery(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    percent = _first_float(data, "battery_percent", "battery", "bat", "soc")
    if percent is not None:
        out["percent"] = max(0.0, min(100.0, round(percent, 2)))
    voltage_mv = _first_int(data, "battery_voltage_mv", "vbat_mv")
    if voltage_mv is not None and voltage_mv > 0:
        out["voltage_mv"] = voltage_mv
    charging = _first_bool(data, "charging", "is_charging", "charge")
    if charging is not None:
        out["charging"] = charging
    return out


def _extract_network(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rssi = _first_float(data, "rssi", "rssi_dbm")
    if rssi is not None:
        out["rssi_dbm"] = round(rssi, 2)
    rsrp = _first_float(data, "rsrp", "rsrp_dbm")
    if rsrp is not None:
        out["rsrp_dbm"] = round(rsrp, 2)
    rsrq = _first_float(data, "rsrq", "rsrq_db")
    if rsrq is not None:
        out["rsrq_db"] = round(rsrq, 2)
    snr = _first_float(data, "snr", "snr_db")
    if snr is not None:
        out["snr_db"] = round(snr, 2)
    signal_level = _first_int(data, "signal_level")
    if signal_level is not None:
        out["signal_level"] = signal_level
    network_type = _first_text(data, "network_type", "net_type", "rat")
    if network_type:
        out["network_type"] = network_type
    return out


def _extract_location(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lat = _first_float(data, "lat", "latitude")
    lon = _first_float(data, "lon", "lng", "longitude")
    if lat is not None and lon is not None:
        out["lat"] = round(lat, 7)
        out["lon"] = round(lon, 7)
    accuracy = _first_float(data, "accuracy_m", "gps_accuracy", "location_accuracy")
    if accuracy is not None and accuracy >= 0:
        out["accuracy_m"] = round(accuracy, 2)
    altitude = _first_float(data, "altitude_m", "altitude")
    if altitude is not None:
        out["altitude_m"] = round(altitude, 2)
    return out


def _extract_motion(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    heading = _first_float(data, "heading_deg", "heading", "yaw")
    if heading is not None:
        out["heading_deg"] = round(heading % 360.0, 2)
    speed = _first_float(data, "speed_mps", "speed")
    if speed is not None and speed >= 0:
        out["speed_mps"] = round(speed, 2)
    moving = _first_bool(data, "moving", "is_moving")
    if moving is not None:
        out["moving"] = moving
    steps = _first_int(data, "step_count", "steps")
    if steps is not None and steps >= 0:
        out["step_count"] = steps
    return out


def _extract_imu(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    accel = _extract_triplet(data, "accel", "acc", "accelerometer")
    if accel:
        out["accelerometer_mps2"] = accel
    gyro = _extract_triplet(data, "gyro", "gyroscope")
    if gyro:
        out["gyroscope_dps"] = gyro
    mag = _extract_triplet(data, "mag", "magnetometer")
    if mag:
        out["magnetometer_ut"] = mag
    return out


def _extract_system(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    temp = _first_float(data, "temperature_c", "temp_c", "cpu_temp")
    if temp is not None:
        out["temperature_c"] = round(temp, 2)
    cpu = _first_float(data, "cpu_percent", "cpu_usage")
    if cpu is not None:
        out["cpu_percent"] = max(0.0, min(100.0, round(cpu, 2)))
    memory = _first_float(data, "memory_percent", "mem_percent", "memory_usage")
    if memory is not None:
        out["memory_percent"] = max(0.0, min(100.0, round(memory, 2)))
    return out


def _extract_triplet(data: dict[str, Any], *prefixes: str) -> dict[str, float]:
    axis_payload: dict[str, Any] | None = None
    for key in prefixes:
        value = data.get(key)
        if isinstance(value, dict):
            axis_payload = value
            break
    if axis_payload is None:
        for key in ("imu", "sensors"):
            block = data.get(key)
            if not isinstance(block, dict):
                continue
            for name in prefixes:
                value = block.get(name)
                if isinstance(value, dict):
                    axis_payload = value
                    break
            if axis_payload is not None:
                break

    x = _first_float(data, *[f"{name}_x" for name in prefixes])
    y = _first_float(data, *[f"{name}_y" for name in prefixes])
    z = _first_float(data, *[f"{name}_z" for name in prefixes])
    if axis_payload is not None:
        if x is None:
            x = _to_float(axis_payload.get("x"))
        if y is None:
            y = _to_float(axis_payload.get("y"))
        if z is None:
            z = _to_float(axis_payload.get("z"))
    if x is None and y is None and z is None:
        return {}
    return {
        "x": round(float(x or 0.0), 4),
        "y": round(float(y or 0.0), 4),
        "z": round(float(z or 0.0), 4),
    }


def _first_float(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _deep_get(data, key)
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _deep_get(data, key)
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return None


def _first_bool(data: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = _deep_get(data, key)
        parsed = _to_bool(value)
        if parsed is not None:
            return parsed
    return None


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _deep_get(data, key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _deep_get(data: dict[str, Any], dotted_key: str) -> Any:
    if dotted_key in data:
        return data.get(dotted_key)
    if "." not in dotted_key:
        return None
    cur: Any = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _now_ms() -> int:
    return int(time.time() * 1000)

from nanobot.hardware.runtime.telemetry import normalize_telemetry_payload


def test_normalize_telemetry_payload_extracts_core_fields() -> None:
    result = normalize_telemetry_payload(
        {
            "battery": 88,
            "rssi": -70,
            "lat": 31.2304,
            "lon": 121.4737,
            "imu": {
                "accel": {"x": 0.1, "y": 0.2, "z": 9.8},
                "gyro": {"x": 0.01, "y": 0.02, "z": 0.03},
            },
            "temperature_c": 36.5,
        },
        ts_ms=1234,
    )

    assert result["schema_version"] == "opencane.telemetry.v1"
    assert result["ts_ms"] == 1234
    assert result["battery"]["percent"] == 88.0
    assert result["network"]["rssi_dbm"] == -70.0
    assert result["location"]["lat"] == 31.2304
    assert result["location"]["lon"] == 121.4737
    assert result["imu"]["accelerometer_mps2"]["z"] == 9.8
    assert result["imu"]["gyroscope_dps"]["x"] == 0.01
    assert result["system"]["temperature_c"] == 36.5


def test_normalize_telemetry_payload_returns_empty_for_unsupported_input() -> None:
    assert normalize_telemetry_payload({}, ts_ms=1) == {}
    assert normalize_telemetry_payload(None, ts_ms=1) == {}

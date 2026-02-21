"""Runtime observability payload builders for control API."""

from __future__ import annotations

import time
from typing import Any


def _to_float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def runtime_observability_payload(
    runtime_status: dict[str, Any],
    *,
    task_failure_rate_max: float,
    safety_downgrade_rate_max: float,
    device_offline_rate_max: float,
    ingest_queue_utilization_max: float,
    min_task_total_for_alert: int = 10,
    min_safety_applied_for_alert: int = 10,
    min_devices_total_for_alert: int = 1,
    ingest_rejected_active_queue_depth_min: int = 1,
    ingest_rejected_active_utilization_min: float = 0.2,
) -> dict[str, Any]:
    digital_task = runtime_status.get("digital_task")
    digital = digital_task if isinstance(digital_task, dict) else {}
    safety_data = runtime_status.get("safety")
    safety = safety_data if isinstance(safety_data, dict) else {}
    devices_data = runtime_status.get("devices")
    devices = devices_data if isinstance(devices_data, list) else []
    lifelog_data = runtime_status.get("lifelog")
    lifelog = lifelog_data if isinstance(lifelog_data, dict) else {}
    ingest_data = lifelog.get("ingest_queue")
    ingest_queue = ingest_data if isinstance(ingest_data, dict) else {}
    runtime_metrics_data = runtime_status.get("metrics")
    runtime_metrics = runtime_metrics_data if isinstance(runtime_metrics_data, dict) else {}

    task_total = _to_int_value(digital.get("total"), 0)
    task_failed = _to_int_value(digital.get("failed"), 0)
    task_timeout = _to_int_value(digital.get("timeout"), 0)
    task_canceled = _to_int_value(digital.get("canceled"), 0)
    task_failures = max(0, task_failed + task_timeout + task_canceled)
    task_failure_rate = (float(task_failures) / float(task_total)) if task_total > 0 else 0.0

    safety_applied = _to_int_value(safety.get("applied"), 0)
    safety_downgraded = _to_int_value(safety.get("downgraded"), 0)
    safety_downgrade_rate = (
        float(safety_downgraded) / float(safety_applied) if safety_applied > 0 else 0.0
    )

    devices_total = len(devices)
    offline_states = {"closed", "offline", "disconnected"}
    devices_offline = sum(
        1
        for item in devices
        if isinstance(item, dict) and str(item.get("state") or "").strip().lower() in offline_states
    )
    device_offline_rate = (
        float(devices_offline) / float(devices_total) if devices_total > 0 else 0.0
    )

    ingest_depth = _to_int_value(ingest_queue.get("depth"), 0)
    ingest_max_size = max(1, _to_int_value(ingest_queue.get("max_size"), 1))
    ingest_queue_utilization = float(ingest_depth) / float(ingest_max_size)
    ingest_rejected_total = _to_int_value(ingest_queue.get("rejected_total"), 0)
    ingest_dropped_total = _to_int_value(ingest_queue.get("dropped_total"), 0)

    voice_turn_total = _to_int_value(runtime_metrics.get("voice_turn_total"), 0)
    voice_turn_failed = _to_int_value(runtime_metrics.get("voice_turn_failed"), 0)
    voice_turn_failure_rate = (
        float(voice_turn_failed) / float(voice_turn_total) if voice_turn_total > 0 else 0.0
    )

    metrics = {
        "task_total": task_total,
        "task_failures": task_failures,
        "task_failure_rate": round(task_failure_rate, 4),
        "safety_applied": safety_applied,
        "safety_downgraded": safety_downgraded,
        "safety_downgrade_rate": round(safety_downgrade_rate, 4),
        "devices_total": devices_total,
        "devices_offline": devices_offline,
        "device_offline_rate": round(device_offline_rate, 4),
        "ingest_queue_depth": ingest_depth,
        "ingest_queue_max_size": ingest_max_size,
        "ingest_queue_utilization": round(ingest_queue_utilization, 4),
        "ingest_queue_rejected_total": ingest_rejected_total,
        "ingest_queue_dropped_total": ingest_dropped_total,
        "voice_turn_total": voice_turn_total,
        "voice_turn_failed": voice_turn_failed,
        "voice_turn_failure_rate": round(voice_turn_failure_rate, 4),
        "voice_turn_avg_latency_ms": round(_to_float_value(runtime_metrics.get("voice_turn_avg_latency_ms"), 0.0), 2),
        "voice_turn_max_latency_ms": round(_to_float_value(runtime_metrics.get("voice_turn_max_latency_ms"), 0.0), 2),
        "stt_avg_latency_ms": round(_to_float_value(runtime_metrics.get("stt_avg_latency_ms"), 0.0), 2),
        "stt_max_latency_ms": round(_to_float_value(runtime_metrics.get("stt_max_latency_ms"), 0.0), 2),
        "agent_avg_latency_ms": round(_to_float_value(runtime_metrics.get("agent_avg_latency_ms"), 0.0), 2),
        "agent_max_latency_ms": round(_to_float_value(runtime_metrics.get("agent_max_latency_ms"), 0.0), 2),
    }
    thresholds = {
        "task_failure_rate_max": float(task_failure_rate_max),
        "safety_downgrade_rate_max": float(safety_downgrade_rate_max),
        "device_offline_rate_max": float(device_offline_rate_max),
        "ingest_queue_utilization_max": float(ingest_queue_utilization_max),
        "min_task_total_for_alert": max(0, int(min_task_total_for_alert)),
        "min_safety_applied_for_alert": max(0, int(min_safety_applied_for_alert)),
        "min_devices_total_for_alert": max(0, int(min_devices_total_for_alert)),
        "ingest_rejected_active_queue_depth_min": max(0, int(ingest_rejected_active_queue_depth_min)),
        "ingest_rejected_active_utilization_min": max(0.0, float(ingest_rejected_active_utilization_min)),
    }

    alerts: list[dict[str, Any]] = []
    if task_total >= max(0, int(min_task_total_for_alert)) and task_failure_rate > task_failure_rate_max:
        alerts.append(
            {
                "metric": "task_failure_rate",
                "value": round(task_failure_rate, 4),
                "threshold": float(task_failure_rate_max),
            }
        )
    if safety_applied >= max(0, int(min_safety_applied_for_alert)) and safety_downgrade_rate > safety_downgrade_rate_max:
        alerts.append(
            {
                "metric": "safety_downgrade_rate",
                "value": round(safety_downgrade_rate, 4),
                "threshold": float(safety_downgrade_rate_max),
            }
        )
    if devices_total >= max(0, int(min_devices_total_for_alert)) and device_offline_rate > device_offline_rate_max:
        alerts.append(
            {
                "metric": "device_offline_rate",
                "value": round(device_offline_rate, 4),
                "threshold": float(device_offline_rate_max),
            }
        )
    if ingest_queue_utilization > ingest_queue_utilization_max:
        alerts.append(
            {
                "metric": "ingest_queue_utilization",
                "value": round(ingest_queue_utilization, 4),
                "threshold": float(ingest_queue_utilization_max),
            }
        )
    queue_active_for_rejected_alert = (
        ingest_depth >= max(0, int(ingest_rejected_active_queue_depth_min))
        or ingest_queue_utilization >= max(0.0, float(ingest_rejected_active_utilization_min))
    )
    if ingest_rejected_total > 0 and queue_active_for_rejected_alert:
        alerts.append(
            {
                "metric": "ingest_queue_rejected_total",
                "value": int(ingest_rejected_total),
                "threshold": 0,
            }
        )
    if ingest_dropped_total > 0 and queue_active_for_rejected_alert:
        alerts.append(
            {
                "metric": "ingest_queue_dropped_total",
                "value": int(ingest_dropped_total),
                "threshold": 0,
            }
        )

    return {
        "success": True,
        "healthy": len(alerts) == 0,
        "ts": int(time.time() * 1000),
        "metrics": metrics,
        "thresholds": thresholds,
        "alerts": alerts,
    }


def build_observability_history_payload(
    *,
    samples: list[dict[str, Any]],
    now_ms: int,
    window_seconds: int,
    bucket_seconds: int,
    max_points: int,
    include_raw: bool,
) -> dict[str, Any]:
    window_seconds = max(60, min(24 * 60 * 60, int(window_seconds)))
    bucket_seconds = max(5, min(60 * 60, int(bucket_seconds)))
    max_points = max(1, min(1000, int(max_points)))

    window_ms = window_seconds * 1000
    bucket_ms = bucket_seconds * 1000
    if bucket_ms <= 0:
        bucket_ms = 5000
    total_buckets = max(1, (window_ms + bucket_ms - 1) // bucket_ms)
    if total_buckets > max_points:
        bucket_ms = max(1000, (window_ms + max_points - 1) // max_points)
        total_buckets = max(1, (window_ms + bucket_ms - 1) // bucket_ms)
    effective_bucket_seconds = max(1, int(round(float(bucket_ms) / 1000.0)))

    start_ts = int(now_ms - window_ms)
    window_samples = [
        item
        for item in samples
        if int(_to_int_value(item.get("ts"), 0)) >= start_ts
    ]
    window_samples.sort(key=lambda item: int(_to_int_value(item.get("ts"), 0)))

    bucket_map: dict[int, dict[str, Any]] = {}
    for sample in window_samples:
        sample_ts = int(_to_int_value(sample.get("ts"), 0))
        idx = max(0, int((sample_ts - start_ts) // bucket_ms))
        metrics = sample.get("metrics")
        metric_map = metrics if isinstance(metrics, dict) else {}
        bucket = bucket_map.setdefault(
            idx,
            {
                "count": 0,
                "healthy_count": 0,
                "sum_task_failure_rate": 0.0,
                "max_task_failure_rate": 0.0,
                "sum_safety_downgrade_rate": 0.0,
                "max_safety_downgrade_rate": 0.0,
                "sum_device_offline_rate": 0.0,
                "max_device_offline_rate": 0.0,
                "sum_ingest_queue_utilization": 0.0,
                "max_ingest_queue_utilization": 0.0,
                "sum_voice_turn_failure_rate": 0.0,
                "max_voice_turn_failure_rate": 0.0,
                "sum_voice_turn_avg_latency_ms": 0.0,
                "max_voice_turn_avg_latency_ms": 0.0,
                "sum_stt_avg_latency_ms": 0.0,
                "max_stt_avg_latency_ms": 0.0,
                "sum_agent_avg_latency_ms": 0.0,
                "max_agent_avg_latency_ms": 0.0,
            },
        )
        task_failure_rate = _to_float_value(metric_map.get("task_failure_rate"), 0.0)
        safety_downgrade_rate = _to_float_value(metric_map.get("safety_downgrade_rate"), 0.0)
        device_offline_rate = _to_float_value(metric_map.get("device_offline_rate"), 0.0)
        ingest_queue_utilization = _to_float_value(metric_map.get("ingest_queue_utilization"), 0.0)
        voice_turn_failure_rate = _to_float_value(metric_map.get("voice_turn_failure_rate"), 0.0)
        voice_turn_avg_latency_ms = _to_float_value(metric_map.get("voice_turn_avg_latency_ms"), 0.0)
        stt_avg_latency_ms = _to_float_value(metric_map.get("stt_avg_latency_ms"), 0.0)
        agent_avg_latency_ms = _to_float_value(metric_map.get("agent_avg_latency_ms"), 0.0)
        bucket["count"] += 1
        bucket["healthy_count"] += 1 if bool(sample.get("healthy")) else 0
        bucket["sum_task_failure_rate"] += task_failure_rate
        bucket["max_task_failure_rate"] = max(float(bucket["max_task_failure_rate"]), task_failure_rate)
        bucket["sum_safety_downgrade_rate"] += safety_downgrade_rate
        bucket["max_safety_downgrade_rate"] = max(
            float(bucket["max_safety_downgrade_rate"]),
            safety_downgrade_rate,
        )
        bucket["sum_device_offline_rate"] += device_offline_rate
        bucket["max_device_offline_rate"] = max(float(bucket["max_device_offline_rate"]), device_offline_rate)
        bucket["sum_ingest_queue_utilization"] += ingest_queue_utilization
        bucket["max_ingest_queue_utilization"] = max(
            float(bucket["max_ingest_queue_utilization"]),
            ingest_queue_utilization,
        )
        bucket["sum_voice_turn_failure_rate"] += voice_turn_failure_rate
        bucket["max_voice_turn_failure_rate"] = max(
            float(bucket["max_voice_turn_failure_rate"]),
            voice_turn_failure_rate,
        )
        bucket["sum_voice_turn_avg_latency_ms"] += voice_turn_avg_latency_ms
        bucket["max_voice_turn_avg_latency_ms"] = max(
            float(bucket["max_voice_turn_avg_latency_ms"]),
            voice_turn_avg_latency_ms,
        )
        bucket["sum_stt_avg_latency_ms"] += stt_avg_latency_ms
        bucket["max_stt_avg_latency_ms"] = max(float(bucket["max_stt_avg_latency_ms"]), stt_avg_latency_ms)
        bucket["sum_agent_avg_latency_ms"] += agent_avg_latency_ms
        bucket["max_agent_avg_latency_ms"] = max(
            float(bucket["max_agent_avg_latency_ms"]),
            agent_avg_latency_ms,
        )

    points: list[dict[str, Any]] = []
    for idx in sorted(bucket_map):
        bucket = bucket_map[idx]
        count = max(1, int(bucket["count"]))
        ts_start = int(start_ts + idx * bucket_ms)
        ts_end = int(min(start_ts + (idx + 1) * bucket_ms - 1, now_ms))
        points.append(
            {
                "bucket_index": int(idx),
                "ts_start": ts_start,
                "ts_end": ts_end,
                "count": int(bucket["count"]),
                "healthy_ratio": round(float(bucket["healthy_count"]) / float(count), 4),
                "task_failure_rate_avg": round(float(bucket["sum_task_failure_rate"]) / float(count), 4),
                "task_failure_rate_max": round(float(bucket["max_task_failure_rate"]), 4),
                "safety_downgrade_rate_avg": round(
                    float(bucket["sum_safety_downgrade_rate"]) / float(count),
                    4,
                ),
                "safety_downgrade_rate_max": round(float(bucket["max_safety_downgrade_rate"]), 4),
                "device_offline_rate_avg": round(float(bucket["sum_device_offline_rate"]) / float(count), 4),
                "device_offline_rate_max": round(float(bucket["max_device_offline_rate"]), 4),
                "ingest_queue_utilization_avg": round(
                    float(bucket["sum_ingest_queue_utilization"]) / float(count),
                    4,
                ),
                "ingest_queue_utilization_max": round(float(bucket["max_ingest_queue_utilization"]), 4),
                "voice_turn_failure_rate_avg": round(
                    float(bucket["sum_voice_turn_failure_rate"]) / float(count),
                    4,
                ),
                "voice_turn_failure_rate_max": round(float(bucket["max_voice_turn_failure_rate"]), 4),
                "voice_turn_avg_latency_ms_avg": round(
                    float(bucket["sum_voice_turn_avg_latency_ms"]) / float(count),
                    2,
                ),
                "voice_turn_avg_latency_ms_max": round(float(bucket["max_voice_turn_avg_latency_ms"]), 2),
                "stt_avg_latency_ms_avg": round(float(bucket["sum_stt_avg_latency_ms"]) / float(count), 2),
                "stt_avg_latency_ms_max": round(float(bucket["max_stt_avg_latency_ms"]), 2),
                "agent_avg_latency_ms_avg": round(float(bucket["sum_agent_avg_latency_ms"]) / float(count), 2),
                "agent_avg_latency_ms_max": round(float(bucket["max_agent_avg_latency_ms"]), 2),
            }
        )

    latest = window_samples[-1] if window_samples else None
    earliest = window_samples[0] if window_samples else None
    latest_metrics = latest.get("metrics") if isinstance(latest, dict) else {}
    earliest_metrics = earliest.get("metrics") if isinstance(earliest, dict) else {}
    if not isinstance(latest_metrics, dict):
        latest_metrics = {}
    if not isinstance(earliest_metrics, dict):
        earliest_metrics = {}

    healthy_ratio = (
        float(sum(1 for item in window_samples if bool(item.get("healthy")))) / float(len(window_samples))
        if window_samples
        else 1.0
    )
    summary = {
        "sample_count": len(window_samples),
        "point_count": len(points),
        "healthy_ratio": round(healthy_ratio, 4),
        "trend": {
            "task_failure_rate_delta": round(
                _to_float_value(latest_metrics.get("task_failure_rate"), 0.0)
                - _to_float_value(earliest_metrics.get("task_failure_rate"), 0.0),
                4,
            ),
            "safety_downgrade_rate_delta": round(
                _to_float_value(latest_metrics.get("safety_downgrade_rate"), 0.0)
                - _to_float_value(earliest_metrics.get("safety_downgrade_rate"), 0.0),
                4,
            ),
            "device_offline_rate_delta": round(
                _to_float_value(latest_metrics.get("device_offline_rate"), 0.0)
                - _to_float_value(earliest_metrics.get("device_offline_rate"), 0.0),
                4,
            ),
            "ingest_queue_utilization_delta": round(
                _to_float_value(latest_metrics.get("ingest_queue_utilization"), 0.0)
                - _to_float_value(earliest_metrics.get("ingest_queue_utilization"), 0.0),
                4,
            ),
            "voice_turn_failure_rate_delta": round(
                _to_float_value(latest_metrics.get("voice_turn_failure_rate"), 0.0)
                - _to_float_value(earliest_metrics.get("voice_turn_failure_rate"), 0.0),
                4,
            ),
            "voice_turn_avg_latency_ms_delta": round(
                _to_float_value(latest_metrics.get("voice_turn_avg_latency_ms"), 0.0)
                - _to_float_value(earliest_metrics.get("voice_turn_avg_latency_ms"), 0.0),
                2,
            ),
            "stt_avg_latency_ms_delta": round(
                _to_float_value(latest_metrics.get("stt_avg_latency_ms"), 0.0)
                - _to_float_value(earliest_metrics.get("stt_avg_latency_ms"), 0.0),
                2,
            ),
            "agent_avg_latency_ms_delta": round(
                _to_float_value(latest_metrics.get("agent_avg_latency_ms"), 0.0)
                - _to_float_value(earliest_metrics.get("agent_avg_latency_ms"), 0.0),
                2,
            ),
        },
    }

    output: dict[str, Any] = {
        "success": True,
        "window_seconds": window_seconds,
        "bucket_seconds": effective_bucket_seconds,
        "max_points": max_points,
        "start_ts": start_ts,
        "end_ts": now_ms,
        "count": len(points),
        "points": points,
        "summary": summary,
    }
    if latest:
        output["latest"] = latest
    if include_raw:
        output["raw_samples"] = window_samples
    return output

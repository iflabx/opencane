"""Helpers to redact sensitive values from structured payloads."""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "token",
    "device_token",
    "api_key",
    "authorization",
    "password",
    "secret",
}


def mask_value(value: Any, *, keep_prefix: int = 2, keep_suffix: int = 2) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep_prefix + keep_suffix:
        return "*" * len(text)
    return f"{text[:keep_prefix]}{'*' * (len(text) - keep_prefix - keep_suffix)}{text[-keep_suffix:]}"


def redact_sensitive_map(data: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in data.items():
        lower_key = str(key).strip().lower()
        if lower_key in SENSITIVE_KEYS:
            output[key] = mask_value(value)
            continue
        if isinstance(value, dict):
            output[key] = redact_sensitive_map(value)
            continue
        if isinstance(value, list):
            masked_items: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    masked_items.append(redact_sensitive_map(item))
                else:
                    masked_items.append(item)
            output[key] = masked_items
            continue
        output[key] = value
    return output

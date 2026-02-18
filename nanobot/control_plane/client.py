"""Control-plane client with cache and fallback behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

JsonFetcher = Callable[[str, dict[str, Any], dict[str, str], float], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class _CacheEntry:
    value: dict[str, Any]
    expires_at_ms: int


class ControlPlaneClient:
    """Fetches runtime/device policy from remote control plane with local cache fallback."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "",
        api_token: str = "",
        runtime_config_path: str = "/v1/control/runtime_config",
        device_policy_path: str = "/v1/control/device_policy",
        timeout_seconds: float = 3.0,
        cache_ttl_seconds: int = 30,
        fallback_runtime_config: dict[str, Any] | None = None,
        fetcher: JsonFetcher | None = None,
    ) -> None:
        self.enabled = bool(enabled and str(base_url or "").strip())
        self.base_url = str(base_url or "").rstrip("/")
        self.api_token = str(api_token or "").strip()
        self.runtime_config_path = str(runtime_config_path or "/v1/control/runtime_config").strip()
        self.device_policy_path = str(device_policy_path or "/v1/control/device_policy").strip()
        self.timeout_seconds = max(0.2, float(timeout_seconds))
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.fallback_runtime_config = dict(fallback_runtime_config or {})
        self._fetcher = fetcher or self._http_fetch_json
        self._runtime_cache: _CacheEntry | None = None
        self._device_cache: dict[str, _CacheEntry] = {}
        self._last_error: str = ""

    async def fetch_runtime_config(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return {
                "success": True,
                "source": "disabled",
                "data": dict(self.fallback_runtime_config),
            }
        now = _now_ms()
        if not force_refresh and self._runtime_cache and now <= self._runtime_cache.expires_at_ms:
            return {"success": True, "source": "cache", "data": dict(self._runtime_cache.value)}

        headers = _auth_headers(self.api_token)
        try:
            payload = await self._fetcher(
                self._full_url(self.runtime_config_path),
                {},
                headers,
                self.timeout_seconds,
            )
            data = payload if isinstance(payload, dict) else {}
            self._runtime_cache = _CacheEntry(
                value=dict(data),
                expires_at_ms=now + self.cache_ttl_seconds * 1000,
            )
            self._last_error = ""
            return {"success": True, "source": "remote", "data": dict(data)}
        except Exception as e:
            self._last_error = str(e)
            if self._runtime_cache:
                return {
                    "success": True,
                    "source": "stale_cache",
                    "data": dict(self._runtime_cache.value),
                    "warning": str(e),
                }
            return {
                "success": True,
                "source": "fallback",
                "data": dict(self.fallback_runtime_config),
                "warning": str(e),
            }

    async def fetch_device_policy(self, *, device_id: str, force_refresh: bool = False) -> dict[str, Any]:
        device = str(device_id or "").strip()
        if not device:
            return {"success": False, "error": "device_id is required"}
        if not self.enabled:
            return {"success": True, "source": "disabled", "data": {}}

        now = _now_ms()
        cached = self._device_cache.get(device)
        if not force_refresh and cached and now <= cached.expires_at_ms:
            return {"success": True, "source": "cache", "data": dict(cached.value)}

        headers = _auth_headers(self.api_token)
        try:
            payload = await self._fetcher(
                self._full_url(self.device_policy_path),
                {"device_id": device},
                headers,
                self.timeout_seconds,
            )
            data = payload if isinstance(payload, dict) else {}
            self._device_cache[device] = _CacheEntry(
                value=dict(data),
                expires_at_ms=now + self.cache_ttl_seconds * 1000,
            )
            self._last_error = ""
            return {"success": True, "source": "remote", "data": dict(data)}
        except Exception as e:
            self._last_error = str(e)
            if cached:
                return {
                    "success": True,
                    "source": "stale_cache",
                    "data": dict(cached.value),
                    "warning": str(e),
                }
            return {"success": False, "error": str(e)}

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "runtime_cache": bool(self._runtime_cache is not None),
            "device_cache_size": len(self._device_cache),
            "last_error": self._last_error,
        }

    async def close(self) -> None:
        return None

    def _full_url(self, path: str) -> str:
        value = str(path or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if not value.startswith("/"):
            value = f"/{value}"
        return f"{self.base_url}{value}"

    async def _http_fetch_json(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}


def _auth_headers(token: str) -> dict[str, str]:
    text = str(token or "").strip()
    if not text:
        return {}
    return {"Authorization": f"Bearer {text}"}


def _now_ms() -> int:
    return int(time.time() * 1000)

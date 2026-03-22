"""Tests for lazy provider exports from opencane.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "opencane.providers", raising=False)
    monkeypatch.delitem(sys.modules, "opencane.providers.litellm_provider", raising=False)

    providers = importlib.import_module("opencane.providers")

    assert "opencane.providers.litellm_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "LiteLLMProvider",
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "opencane.providers", raising=False)
    monkeypatch.delitem(sys.modules, "opencane.providers.litellm_provider", raising=False)

    namespace: dict[str, object] = {}
    exec("from opencane.providers import LiteLLMProvider", namespace)

    assert namespace["LiteLLMProvider"].__name__ == "LiteLLMProvider"
    assert "opencane.providers.litellm_provider" in sys.modules

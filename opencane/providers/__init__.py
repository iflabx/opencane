"""LLM provider abstraction module."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from opencane.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider"]

_LAZY_IMPORTS = {
    "LiteLLMProvider": ".litellm_provider",
}
_LAZY_MODULES = {
    "transcription": ".transcription",
    "tts": ".tts",
}

if TYPE_CHECKING:
    from opencane.providers.litellm_provider import LiteLLMProvider


def __getattr__(name: str):
    """Lazily expose provider implementations without importing all backends up front."""
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is not None:
        module = import_module(module_name, __name__)
        return getattr(module, name)

    module_name = _LAZY_MODULES.get(name)
    if module_name is not None:
        return import_module(module_name, __name__)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from __future__ import annotations

import pytest

from opencane.agent.tools.web import WebSearchTool


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):  # type: ignore[no-untyped-def]
        return {
            "web": {
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "description": "Example result",
                    }
                ]
            }
        }


class _FakeAsyncClient:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return None

    async def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return _FakeResponse()


@pytest.mark.asyncio
async def test_web_search_resolves_env_key_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = WebSearchTool(api_key=None)
    monkeypatch.setenv("BRAVE_API_KEY", "env-key")
    monkeypatch.setattr("opencane.agent.tools.web.httpx.AsyncClient", lambda: _FakeAsyncClient())

    result = await tool.execute("hello")
    assert "Results for: hello" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_web_search_missing_key_error_mentions_config_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = WebSearchTool(api_key=None)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    result = await tool.execute("hello")
    assert "tools.web.search.apiKey" in result
    assert "BRAVE_API_KEY" in result

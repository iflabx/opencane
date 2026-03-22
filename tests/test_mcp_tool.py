import asyncio
import sys
from types import SimpleNamespace

import pytest

from opencane.agent.tools.mcp import MCPToolWrapper


def test_wrapper_preserves_non_nullable_unions() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [{"type": "string"}, {"type": "integer"}],
                }
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["value"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]


def test_wrapper_normalizes_nullable_property_type_union() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {"type": "string", "nullable": True}


def test_wrapper_normalizes_nullable_property_anyof() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "optional name",
                },
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {
        "type": "string",
        "description": "optional name",
        "nullable": True,
    }


@pytest.mark.asyncio
async def test_wrapper_execute_times_out_slow_mcp_call(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeTypes:
        class TextContent:
            def __init__(self, text: str):
                self.text = text

    monkeypatch.setitem(sys.modules, "mcp", SimpleNamespace(types=_FakeTypes))
    monkeypatch.setattr("opencane.agent.tools.mcp.MCP_TOOL_TIMEOUT", 0.01)

    class _SlowSession:
        async def call_tool(self, _name: str, arguments: dict):  # type: ignore[no-untyped-def]
            del arguments
            await asyncio.sleep(0.1)
            return SimpleNamespace(content=[])

    wrapper = MCPToolWrapper(
        _SlowSession(),
        "test",
        SimpleNamespace(
            name="demo",
            description="demo tool",
            inputSchema={"type": "object", "properties": {}},
        ),
    )

    result = await wrapper.execute()
    assert "timed out" in result


@pytest.mark.asyncio
async def test_wrapper_execute_renders_text_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeTypes:
        class TextContent:
            def __init__(self, text: str):
                self.text = text

    monkeypatch.setitem(sys.modules, "mcp", SimpleNamespace(types=_FakeTypes))

    class _Session:
        async def call_tool(self, _name: str, arguments: dict):  # type: ignore[no-untyped-def]
            del arguments
            return SimpleNamespace(
                content=[_FakeTypes.TextContent("line1"), {"type": "other"}]
            )

    wrapper = MCPToolWrapper(
        _Session(),
        "test",
        SimpleNamespace(
            name="demo",
            description="demo tool",
            inputSchema={"type": "object", "properties": {}},
        ),
    )

    result = await wrapper.execute()
    assert "line1" in result
    assert "{'type': 'other'}" in result

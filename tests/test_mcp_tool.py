from types import SimpleNamespace

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

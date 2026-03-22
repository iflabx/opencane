from __future__ import annotations

from pathlib import Path

import pytest

from opencane.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool


@pytest.mark.asyncio
async def test_write_and_read_file_tools_resolve_relative_paths_to_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    other_dir = tmp_path / "other"
    other_dir.mkdir(parents=True)
    monkeypatch.chdir(other_dir)

    write_tool = WriteFileTool(workspace=workspace)
    read_tool = ReadFileTool(workspace=workspace)

    write_result = await write_tool.execute(path="notes/today.txt", content="hello workspace")
    read_result = await read_tool.execute(path="notes/today.txt")

    assert (workspace / "notes" / "today.txt").read_text(encoding="utf-8") == "hello workspace"
    assert str(workspace / "notes" / "today.txt") in write_result
    assert read_result == "hello workspace"


@pytest.mark.asyncio
async def test_edit_and_list_dir_tools_resolve_relative_paths_to_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "plan.md").write_text("alpha", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    edit_tool = EditFileTool(workspace=workspace)
    list_tool = ListDirTool(workspace=workspace)

    edit_result = await edit_tool.execute(path="docs/plan.md", old_text="alpha", new_text="beta")
    list_result = await list_tool.execute(path="docs")

    assert (workspace / "docs" / "plan.md").read_text(encoding="utf-8") == "beta"
    assert str(workspace / "docs" / "plan.md") in edit_result
    assert "plan.md" in list_result


@pytest.mark.asyncio
async def test_read_file_tool_still_enforces_allowed_dir_with_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    read_tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
    result = await read_tool.execute(path="../outside.txt")

    assert result.startswith("Error: Path ../outside.txt is outside allowed directory")


@pytest.mark.asyncio
async def test_allowed_dir_check_rejects_startswith_path_bypass(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    evil_dir = tmp_path / "workspace_evil"
    evil_dir.mkdir(parents=True)
    secret = evil_dir / "secret.txt"
    secret.write_text("leak", encoding="utf-8")

    read_tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
    result = await read_tool.execute(path=str(secret))

    assert result.startswith("Error: Path ")
    assert "outside allowed directory" in result


@pytest.mark.asyncio
async def test_edit_file_tool_not_found_reports_best_match(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    target = workspace / "docs" / "plan.md"
    target.parent.mkdir(parents=True)
    target.write_text("alpha line\nbeta line\n", encoding="utf-8")

    edit_tool = EditFileTool(workspace=workspace)
    result = await edit_tool.execute(
        path="docs/plan.md",
        old_text="alpha lin\nbeta line\n",
        new_text="patched",
    )

    assert "Best match" in result
    assert "similar" in result
    assert "old_text (provided)" in result


@pytest.mark.asyncio
async def test_read_file_tool_returns_multimodal_blocks_for_image(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    image_file = workspace / "photo.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-png")

    tool = ReadFileTool(workspace=workspace)
    result = await tool.execute(path="photo.png")

    assert isinstance(result, list)
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result[0]["_meta"]["path"] == str(image_file)
    assert result[1] == {"type": "text", "text": "(Image file: photo.png)"}

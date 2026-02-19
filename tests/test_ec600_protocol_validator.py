from pathlib import Path

from nanobot.hardware.validate_protocol import validate_mapping


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _minimal_mapping(*, frozen: bool, include_placeholder: bool) -> str:
    status = "Frozen" if frozen else "Draft"
    placeholder = "待填写" if include_placeholder else "已填写"
    return f"""
## 2. 协议版本与状态
- 当前状态：`{status}`
## 3. 主题（MQTT Topic）映射
{placeholder}
## 4. 统一消息信封映射（Control JSON）
{placeholder}
## 5. 上行事件映射（Device -> Server）
{placeholder}
## 6. 下行指令映射（Server -> Device）
{placeholder}
## 7. 二进制音频包头映射（16 bytes）
{placeholder}
## 8. 重连恢复字段映射（HW-06 联动）
{placeholder}
## 9. 错误码与异常语义映射
{placeholder}
## 11. 冻结清单（Freeze Checklist）
{placeholder}
"""


def test_validate_mapping_allows_placeholders_in_draft(tmp_path: Path) -> None:
    mapping = _write(
        tmp_path / "mapping.md",
        _minimal_mapping(frozen=False, include_placeholder=True),
    )
    assert validate_mapping(mapping, stage="draft", max_report=5) == 0


def test_validate_mapping_rejects_placeholders_in_freeze(tmp_path: Path) -> None:
    mapping = _write(
        tmp_path / "mapping.md",
        _minimal_mapping(frozen=True, include_placeholder=True),
    )
    assert validate_mapping(mapping, stage="freeze", max_report=5) == 1


def test_validate_mapping_requires_frozen_status_for_freeze_stage(tmp_path: Path) -> None:
    mapping = _write(
        tmp_path / "mapping.md",
        _minimal_mapping(frozen=False, include_placeholder=False),
    )
    assert validate_mapping(mapping, stage="freeze", max_report=5) == 1


def test_validate_mapping_passes_freeze_when_complete(tmp_path: Path) -> None:
    mapping = _write(
        tmp_path / "mapping.md",
        _minimal_mapping(frozen=True, include_placeholder=False),
    )
    assert validate_mapping(mapping, stage="freeze", max_report=5) == 0

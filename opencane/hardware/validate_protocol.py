"""Validation utility for EC600 protocol mapping documents."""

from __future__ import annotations

import argparse
from pathlib import Path

PLACEHOLDER_TOKENS = ("待填写", "Draft")
REQUIRED_SECTIONS = (
    "## 3. 主题（MQTT Topic）映射",
    "## 4. 统一消息信封映射（Control JSON）",
    "## 5. 上行事件映射（Device -> Server）",
    "## 6. 下行指令映射（Server -> Device）",
    "## 7. 二进制音频包头映射（16 bytes）",
    "## 8. 重连恢复字段映射（HW-06 联动）",
    "## 9. 错误码与异常语义映射",
    "## 11. 冻结清单（Freeze Checklist）",
)


def _find_placeholders(text: str) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if any(token in line for token in PLACEHOLDER_TOKENS):
            findings.append((idx, line.strip()))
    return findings


def _print_findings(title: str, lines: list[str]) -> None:
    if not lines:
        return
    print(title)
    for line in lines:
        print(f"  - {line}")


def validate_mapping(path: Path, *, stage: str, max_report: int) -> int:
    if not path.exists():
        print(f"[FAIL] mapping file not found: {path}")
        return 1

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    missing_sections = [sec for sec in REQUIRED_SECTIONS if sec not in text]
    if missing_sections:
        errors.append("missing required sections:")
        for sec in missing_sections:
            errors.append(f"  {sec}")

    placeholders = _find_placeholders(text)
    if stage == "freeze":
        if "当前状态：`Frozen`" not in text:
            errors.append("status is not Frozen (missing `当前状态：`Frozen``)")
        if placeholders:
            errors.append(
                f"found unresolved placeholders ({len(placeholders)}), showing first {max_report}:"
            )
            for ln, content in placeholders[:max_report]:
                errors.append(f"  L{ln}: {content}")
    elif placeholders:
        warnings.append(
            f"found unresolved placeholders ({len(placeholders)}), draft stage allows this."
        )
        for ln, content in placeholders[:max_report]:
            warnings.append(f"  L{ln}: {content}")

    if errors:
        _print_findings("[FAIL]", errors)
        if warnings:
            _print_findings("[WARN]", warnings)
        return 1

    print("[OK] mapping structure validation passed")
    if warnings:
        _print_findings("[WARN]", warnings)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EC600 protocol mapping markdown.")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("EC600_PROTOCOL_MAPPING_TEMPLATE.md"),
        help="Path to EC600 mapping markdown file",
    )
    parser.add_argument(
        "--stage",
        choices=["draft", "freeze"],
        default="draft",
        help="Validation strictness. freeze requires zero placeholders and Frozen status.",
    )
    parser.add_argument(
        "--max-report",
        type=int,
        default=20,
        help="Maximum placeholder lines to print in report.",
    )
    args = parser.parse_args()

    return validate_mapping(
        args.mapping,
        stage=args.stage,
        max_report=max(1, args.max_report),
    )


if __name__ == "__main__":
    raise SystemExit(main())

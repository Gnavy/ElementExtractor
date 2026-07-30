#!/usr/bin/env python3
"""
Parse Case2 fill_logic_rules textarea: natural language + ---CALC--- block.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CALC_START = re.compile(r"^---CALC---\s*$", re.MULTILINE)
_CALC_END = re.compile(r"^---END---\s*$", re.MULTILINE)


def split_rules_text(text: str) -> tuple[str, str]:
    """Return (narrative_md, calc_block_body)."""
    raw = (text or "").strip()
    if not raw:
        return "", ""

    start = _CALC_START.search(raw)
    if not start:
        return raw, ""

    narrative = raw[: start.start()].strip()
    rest = raw[start.end() :]
    end = _CALC_END.search(rest)
    calc_body = rest[: end.start()].strip() if end else rest.strip()
    return narrative, calc_body


def parse_calc_block(calc_body: str) -> list[dict[str, Any]]:
    """Parse CALC lines into structured rules."""
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for line in (calc_body or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        op = parts[0].lower()
        if op not in ("sum", "sum_if_missing", "diff"):
            continue
        sheet, target_label, sources_raw = parts[1], parts[2], parts[3]
        source_labels = [s.strip() for s in sources_raw.split(",") if s.strip()]
        if not sheet or not target_label or not source_labels:
            continue
        key = (op, sheet, target_label)
        if key in seen:
            continue
        seen.add(key)
        rules.append(
            {
                "op": op,
                "sheet": sheet,
                "target_label": target_label,
                "source_labels": source_labels,
            }
        )
    return rules


def merge_calc_rules(*rule_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for rules in rule_lists:
        for rule in rules:
            key = (rule["op"], rule["sheet"], rule["target_label"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(rule)
    return merged


def build_calc_rules_json(text: str) -> dict[str, Any]:
    _narrative, calc_body = split_rules_text(text)
    return {"schema_version": 1, "rules": parse_calc_block(calc_body)}


def write_fill_rules_files(extract_root: Path, fill_logic_rules: str) -> None:
    """Write inputs/fill_logic_rules.md and inputs/fill_calc_rules.json."""
    narrative, calc_body = split_rules_text(fill_logic_rules)
    inputs_dir = extract_root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    md_parts = ["# 用户填表逻辑与计算规则（优先适用）", ""]
    if narrative:
        md_parts.append(narrative)
    else:
        md_parts.append("（无额外自然语言规则）")
    if calc_body:
        md_parts.extend(
            [
                "",
                "## 计算规则（由 Python 工具执行，勿手算）",
                "",
                "```",
                calc_body,
                "```",
            ]
        )
    (inputs_dir / "fill_logic_rules.md").write_text(
        "\n".join(md_parts) + "\n", encoding="utf-8"
    )

    calc_json = build_calc_rules_json(fill_logic_rules)
    (inputs_dir / "fill_calc_rules.json").write_text(
        json.dumps(calc_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Parse Case2 fill logic rules")
    p.add_argument("--text", help="Rules text")
    p.add_argument("--text-file", type=Path)
    p.add_argument("--out", type=Path, help="Write fill_calc_rules.json")
    args = p.parse_args()
    text = args.text or ""
    if args.text_file and args.text_file.is_file():
        text = args.text_file.read_text(encoding="utf-8")
    result = build_calc_rules_json(text)
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(out, encoding="utf-8")
    else:
        print(out)

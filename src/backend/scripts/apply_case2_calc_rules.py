#!/usr/bin/env python3
"""
Apply structured calc rules to case2_filled_schema.json (sum / sum_if_missing).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


_LABEL_PUNCT_RE = re.compile(r"[:：、,，.。;；]+")
# 模板与规则里「其中/加/减」这类前缀写法不统一（其中应收票据 vs 其中:应收票据）
_LABEL_PREFIX_RE = re.compile(r"^(?:其中|加|减)")


def _norm_label(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = re.sub(r"\s+", "", s)
    s = s.replace("（", "(").replace("）", ")")
    s = _LABEL_PUNCT_RE.sub("", s)
    return s.lower()


def _core_label(text: str) -> str:
    """剥掉「其中/加/减」前缀后的科目主体名，用于最后一档匹配"""
    s = _norm_label(text)
    while True:
        stripped = _LABEL_PREFIX_RE.sub("", s)
        if stripped == s:
            return s
        s = stripped


def _is_empty(v: Any) -> bool:
    return v is None or v == ""


def _to_decimal(v: Any) -> Decimal | None:
    if _is_empty(v):
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _find_item(sheet_data: dict, label: str) -> dict | None:
    target = _norm_label(label)
    for item in sheet_data.get("items") or []:
        if _norm_label(item.get("label") or "") == target:
            return item
        meaning = item.get("meaning") or ""
        if meaning and _norm_label(meaning.split("（")[0]) == target:
            return item
    for item in sheet_data.get("items") or []:
        lbl = _norm_label(item.get("label") or "")
        if target in lbl or lbl in target:
            return item
    core = _core_label(label)
    if core:
        for item in sheet_data.get("items") or []:
            if _core_label(item.get("label") or "") == core:
                return item
    return None


def _value_fields(item: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for key, field in (item.get("fields") or {}).items():
        if not isinstance(field, dict):
            continue
        if "value" not in field or not field.get("cell"):
            continue
        out.append((key, field))
    return out


def _collect_evidence(item: dict | None) -> list[str]:
    if not item:
        return []
    refs = item.get("evidence_refs") or []
    return [str(r) for r in refs if r]


def _apply_rule_to_column(
    rule: dict[str, Any],
    target_item: dict,
    source_items: list[dict],
    col_key: str,
    *,
    op: str,
) -> tuple[bool, str | None, Any]:
    """返回 (是否写入, 跳过原因, 被覆盖的旧值)。

    sum / diff 以规则为准，覆盖已有值并留痕；sum_if_missing 仅在缺值时补。
    """
    target_field = (target_item.get("fields") or {}).get(col_key)
    if not isinstance(target_field, dict):
        return False, "target field missing", None

    current = target_field.get("value")
    if op == "sum_if_missing" and not _is_empty(current):
        return False, "target already filled", None

    values: list[Decimal | None] = []
    evidence: list[str] = []
    for src_item in source_items:
        field = (src_item.get("fields") or {}).get(col_key)
        d = _to_decimal(field.get("value")) if isinstance(field, dict) else None
        values.append(d)
        if d is not None:
            evidence.extend(_collect_evidence(src_item))

    if op == "diff":
        # 差额：第一项减去其余项；任一来源缺值都不算，避免半截差额
        if any(v is None for v in values) or not values:
            return False, "missing source value for diff", None
        total = values[0] - sum(values[1:], Decimal(0))
    else:
        present = [v for v in values if v is not None]
        if not present:
            return False, "no source values", None
        total = sum(present, Decimal(0))
        # 来源不全时的部分和只能补空，不覆盖已有值。
        # 例外：部分和与已填值恰好相等时不算覆盖，照常应用规则把溯源补上——
        # 缺的那个来源在源报表里本就没有这一行（如新鸿没有「应付票据」），
        # 空 ≠ 缺失，此时部分和就是全和。不这么做，合并行会永远拿不到
        # evidence_refs 与「计算规则」标记，被「有值但没有来源证据」硬门禁毙掉。
        if (
            len(present) < len(values)
            and not _is_empty(current)
            and _to_decimal(current) != total
        ):
            return False, "incomplete sources, kept existing value", None

    # Preserve int-like decimals as float/int for JSON
    if total == total.to_integral_value():
        new_val: int | float = int(total)
    else:
        new_val = float(total)

    overwrote = None
    if not _is_empty(current) and _to_decimal(current) != total:
        overwrote = current
    target_field["value"] = new_val
    src_labels = ", ".join(rule.get("source_labels") or [])
    target_item["reason_one_line"] = f"计算规则({op}): {src_labels}"
    merged_refs = list(dict.fromkeys(_collect_evidence(target_item) + evidence))
    if merged_refs:
        target_item["evidence_refs"] = merged_refs
    return True, None, overwrote


def apply_calc_rules(data: dict, rules: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "applied": [],
        "skipped": [],
        "warnings": [],
        "review_flags": [],
    }
    sheets_by_name = {
        (sh.get("sheet") or sh.get("name") or ""): sh for sh in data.get("sheets") or []
    }

    for rule in rules:
        sheet_name = rule.get("sheet") or ""
        sheet_data = sheets_by_name.get(sheet_name)
        if not sheet_data:
            report["skipped"].append(
                {"rule": rule, "reason": f"sheet not found: {sheet_name}"}
            )
            continue

        target_item = _find_item(sheet_data, rule.get("target_label") or "")
        if not target_item:
            report["skipped"].append(
                {"rule": rule, "reason": f"target not found: {rule.get('target_label')}"}
            )
            continue

        source_items: list[dict] = []
        missing_sources: list[str] = []
        for lbl in rule.get("source_labels") or []:
            found = _find_item(sheet_data, lbl)
            if found:
                source_items.append(found)
            else:
                missing_sources.append(lbl)
        if missing_sources:
            # 组成项目不全时求和一定是错的，宁可留空让人工处理，不写部分和
            report["warnings"].append(
                f"{sheet_name}: missing sources {missing_sources} for {rule.get('target_label')}"
            )
            report["skipped"].append(
                {
                    "rule": rule,
                    "reason": f"missing source items: {missing_sources}",
                }
            )
            report["review_flags"].append(
                {
                    "kind": "calc_incomplete_sources",
                    "sheet_name": sheet_name,
                    "target": rule.get("target_label"),
                    "detail": (
                        f"{sheet_name}「{rule.get('target_label')}」的计算规则缺少组成项目 "
                        f"{'、'.join(missing_sources)}，未做计算，该行留空需人工确认"
                    ),
                }
            )
            continue
        if not source_items:
            report["skipped"].append(
                {"rule": rule, "reason": "no source items resolved"}
            )
            continue

        op = rule.get("op", "sum")
        col_keys = {k for k, _ in _value_fields(target_item)}
        for src in source_items:
            col_keys.update(k for k, _ in _value_fields(src))

        for col_key in sorted(col_keys):
            ok, reason, overwrote = _apply_rule_to_column(
                rule,
                target_item,
                source_items,
                col_key,
                op=op,
            )
            cell = ((target_item.get("fields") or {}).get(col_key) or {}).get("cell")
            entry = {
                "op": op,
                "sheet": sheet_name,
                "target": rule.get("target_label"),
                "column": col_key,
                "cell": cell,
            }
            if ok:
                entry["value"] = (
                    (target_item.get("fields") or {}).get(col_key) or {}
                ).get("value")
                if overwrote is not None:
                    entry["overwrote"] = overwrote
                    report["review_flags"].append(
                        {
                            "kind": "calc_overwrote_model_value",
                            "sheet_name": sheet_name,
                            "cell": cell,
                            "detail": (
                                f"{sheet_name} {cell}「{rule.get('target_label')}」"
                                f"按计算规则({op})覆盖了模型填的 {overwrote}，"
                                f"现值 {entry['value']}，请复核以规则口径为准是否正确"
                            ),
                        }
                    )
                report["applied"].append(entry)
            elif reason and reason != "target already filled":
                report["skipped"].append({**entry, "reason": reason})

    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Apply Case2 calc rules to filled schema")
    p.add_argument("--filled", default="outputs/case2_filled_schema.json")
    p.add_argument("--rules", default="inputs/fill_calc_rules.json")
    p.add_argument("--report", default="outputs/calc_rules_report.json")
    p.add_argument("--in-place", action="store_true", default=True)
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    filled_path = (cwd / args.filled).resolve()
    rules_path = (cwd / args.rules).resolve()
    report_path = (cwd / args.report).resolve()

    if not filled_path.is_file():
        raise SystemExit(f"filled schema not found: {filled_path}")
    if not rules_path.is_file():
        rep = {"ok": True, "skipped": True, "reason": "no fill_calc_rules.json"}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False))
        return

    data = json.loads(filled_path.read_text(encoding="utf-8"))
    rules_doc = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = rules_doc.get("rules") or []
    if not rules:
        rep = {"ok": True, "skipped": True, "reason": "empty rules"}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False))
        return

    report = apply_calc_rules(data, rules)
    report["ok"] = True
    report["rule_count"] = len(rules)
    report["applied_count"] = len(report.get("applied") or [])

    filled_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

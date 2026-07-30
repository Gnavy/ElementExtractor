from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.tools.context import write_json
from app.services.case2_review import add_review_flags, append_review_section
from app.services.case2_schema_pipeline import (
    apply_case2_calc_rules,
    backfill_case2_schema,
    validate_case2_backfill,
)
from app.services.case2_template_checks import (
    check_review_flags,
    evaluate_checks,
    read_template_checks,
    summarize,
)


def _report_review_flags(root: Path, filename: str) -> list[dict[str, Any]]:
    path = root / "outputs" / filename
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    flags = data.get("review_flags") if isinstance(data, dict) else None
    return [flag for flag in (flags or []) if isinstance(flag, dict)]


def apply_calc_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = apply_case2_calc_rules(root)
    add_review_flags(
        root,
        _report_review_flags(root, "calc_rules_report.json"),
        stage="apply_calc",
    )
    return {
        "log_lines": [f"calc: {log[-400:]}"],
        "errors": [] if ok else [f"Case2 计算规则失败: {log}"],
        "progress": "计算规则已应用",
    }


def _run_template_checks(root: Path) -> tuple[list[dict[str, Any]], str]:
    """用模板自带的核查检验公式核对产物。只读，不回写公式格。"""
    filled = root / "outputs" / "collection_filled.xlsx"
    if not filled.is_file():
        return [], ""
    try:
        checks = read_template_checks(filled)
        outcomes = evaluate_checks(filled, checks)
    except Exception as exc:  # noqa: BLE001 — 核查失败不应连累任务
        return (
            [
                {
                    "kind": "template_check_unparsed",
                    "detail": f"模板核查检验执行失败，本次未校验：{exc}",
                }
            ],
            "模板核查=执行失败",
        )
    stats = summarize(outcomes)
    write_json(root / "outputs" / "template_check_report.json", {
        "summary": stats,
        "failed": [
            {
                "sheet": o.check.sheet,
                "cell": o.check.cell,
                "message": o.check.message,
                "delta": o.delta,
                "empty_refs": o.empty_refs,
                "suspect_cells": o.delta_matches,
                "solved": (
                    {"cell": o.suggestion[0], "value": o.suggestion[1]}
                    if o.suggestion
                    else None
                ),
            }
            for o in outcomes
            if o.ok is False
        ],
    })
    log = (
        f"模板核查={stats['passed']}/{stats['checks']} 通过"
        f"，未通过 {stats['failed']}，未校验 {stats['unchecked']}"
    )
    return check_review_flags(outcomes), log


def backfill_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = backfill_case2_schema(root)
    br_ok, br_msg = (False, "")
    if ok:
        br_ok, br_msg = validate_case2_backfill(root)
    check_flags, check_log = _run_template_checks(root)
    add_review_flags(
        root,
        _report_review_flags(root, "backfill_report.json") + check_flags,
        stage="backfill",
    )
    # 复核提示只提示，不改变任务成败判定
    review_count = append_review_section(root)
    return {
        "backfill_ok": ok and br_ok,
        "backfill_msg": br_msg or log[-400:],
        "validation_ok": ok and br_ok,
        "validation_msg": br_msg or log,
        "errors": [] if (ok and br_ok) else [f"Case2 回填失败: {br_msg or log}"],
        "log_lines": [
            f"backfill: {log[-300:]}",
            f"validate: {br_msg}",
            check_log or "模板核查=无公式可用",
            f"需人工复核={review_count} 条",
        ],
        "progress": "xlsx 回填完成" if ok else "xlsx 回填失败",
    }


def find_retry_items_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark empty items that might be retried once."""
    schema = state.get("filled_schema") or {}
    rnd = int(state.get("fix_round") or 0)
    to_retry: list[str] = []
    if rnd >= 1:
        return {"items_to_retry": [], "fix_round": rnd}

    for sh in schema.get("sheets") or []:
        for item in sh.get("items") or []:
            fields = item.get("fields") or {}
            nonempty = any(
                isinstance(f, dict) and f.get("value") not in (None, "")
                for f in fields.values()
            )
            reason = (item.get("reason_one_line") or "")
            # Retry once if totally empty without clear "not found" reason
            if not nonempty and "未发现" not in reason and "未找到" not in reason:
                iid = item.get("item_id")
                if iid:
                    to_retry.append(iid)
    # Cap retries to avoid cost explosion
    to_retry = to_retry[:20]
    return {
        "items_to_retry": to_retry,
        "fix_round": rnd + (1 if to_retry else 0),
        "log_lines": [
            f"空 item 待重试={len(to_retry)}" if to_retry else "无需重试空 item"
        ],
    }

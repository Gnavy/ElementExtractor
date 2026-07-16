from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.case2_schema_pipeline import (
    apply_case2_calc_rules,
    backfill_case2_schema,
    validate_case2_backfill,
)


def apply_calc_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = apply_case2_calc_rules(root)
    return {
        "log_lines": [f"calc: {log[-400:]}"],
        "errors": [] if ok else [f"Case2 计算规则失败: {log}"],
        "progress": "计算规则已应用",
    }


def backfill_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = backfill_case2_schema(root)
    br_ok, br_msg = (False, "")
    if ok:
        br_ok, br_msg = validate_case2_backfill(root)
    return {
        "backfill_ok": ok and br_ok,
        "backfill_msg": br_msg or log[-400:],
        "validation_ok": ok and br_ok,
        "validation_msg": br_msg or log,
        "errors": [] if (ok and br_ok) else [f"Case2 回填失败: {br_msg or log}"],
        "log_lines": [f"backfill: {log[-300:]}", f"validate: {br_msg}"],
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

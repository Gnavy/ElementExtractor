from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agents.llm import structured_llm
from app.agents.nodes.case2.evidence import facts_for_fill
from app.agents.prompts import case2 as prompts
from app.agents.schemas.case2_item import Case2BatchFill
from app.agents.tools.context import write_json


_FILL_BATCH_MAX_TOKENS = 4096
_NULL_TEXT = {"", "null", "none", "nil", "n/a", "na"}
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def _batch_items(schema: dict, batch_size: int = 8) -> list[dict[str, Any]]:
    """Build batches of items preserving sheet context."""
    batches: list[dict[str, Any]] = []
    for sh in schema.get("sheets") or []:
        sheet_name = sh.get("sheet") or sh.get("name") or ""
        headers = sh.get("column_headers") or {}
        items = list(sh.get("items") or [])
        for i in range(0, len(items), batch_size):
            chunk = items[i : i + batch_size]
            batches.append(
                {
                    "sheet_name": sheet_name,
                    "column_headers": headers,
                    "items": chunk,
                }
            )
    return batches


def prepare_batches_node(state: dict[str, Any]) -> dict[str, Any]:
    schema = state.get("fill_schema") or {}
    retry_ids = set(state.get("items_to_retry") or [])
    batches = _batch_items(schema, batch_size=6)
    if retry_ids:
        # Rebuild batches only with retry items
        filtered: list[dict[str, Any]] = []
        for b in batches:
            items = [it for it in b["items"] if it.get("item_id") in retry_ids]
            if items:
                filtered.append({**b, "items": items})
        batches = filtered
    return {
        "item_batches": batches,
        "log_lines": [f"待填批次={len(batches)}"],
        "progress": f"准备填报 {len(batches)} 批",
    }


def _normalize_value(value: Any, value_type: str) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _NULL_TEXT:
            return None
        if value_type == "number":
            negative = text.startswith("(") and text.endswith(")")
            number = text.strip("()").replace(",", "").replace("，", "").strip()
            if _NUMBER_RE.fullmatch(number):
                parsed = float(number)
                if negative:
                    parsed = -parsed
                return int(parsed) if parsed.is_integer() else parsed
        return text
    if value_type == "number" and isinstance(value, bool):
        return None
    return value


def _sheet_period_mapping(
    period_mapping: dict[str, Any], sheet_name: str
) -> dict[str, dict[str, Any]]:
    return {
        str(column.get("field_key") or ""): column
        for column in period_mapping.get("columns") or []
        if str(column.get("sheet_name") or "") == sheet_name
        and column.get("field_key")
    }


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        try:
            return float(left) == float(str(right).replace(",", "").strip())
        except (TypeError, ValueError):
            return False
    return str(left).strip() == str(right).strip()


def _same_date(left: Any, right: Any) -> bool:
    left_match = _DATE_RE.search(str(left or ""))
    right_match = _DATE_RE.search(str(right or ""))
    if not left_match or not right_match:
        return str(left or "").strip() == str(right or "").strip()
    return left_match.groups() == right_match.groups()


def fill_one_batch_node(state: dict[str, Any]) -> dict[str, Any]:
    items = state.get("items") or []
    sheet_name = state.get("sheet_name") or ""
    item_ids = {str(item.get("item_id") or "") for item in items}
    period_mapping = state.get("period_mapping") or {}
    facts = facts_for_fill(
        state.get("evidence_catalog") or {},
        item_ids,
        sheet_name=sheet_name,
        period_mapping=period_mapping,
    )
    sheet_periods = _sheet_period_mapping(period_mapping, sheet_name)
    # Slim items for prompt (keep structure)
    slim = []
    for it in items:
        slim.append(
            {
                "item_id": it.get("item_id"),
                "row": it.get("row"),
                "label": it.get("label"),
                "meaning": it.get("meaning"),
                "fields": {
                    k: {
                        "cell": (v or {}).get("cell"),
                        "column_label": (v or {}).get("column_label"),
                        "value_type": (v or {}).get("value_type"),
                        "value": None,
                    }
                    for k, v in (it.get("fields") or {}).items()
                    if isinstance(v, dict)
                },
            }
        )

    llm = structured_llm(Case2BatchFill, method="json_mode")
    result: Case2BatchFill = llm.invoke(
        [
            ("system", prompts.FILL_BATCH_SYSTEM),
            (
                "human",
                prompts.FILL_BATCH_USER.format(
                    task_id=state.get("task_id") or "",
                    sheet_name=sheet_name,
                    column_headers=json.dumps(
                        state.get("column_headers") or {}, ensure_ascii=False
                    ),
                    user_rules=(state.get("user_rules") or "（无）")[:4000],
                    items_json=json.dumps(slim, ensure_ascii=False, indent=2),
                    period_mapping_json=json.dumps(
                        [
                            column
                            for column in period_mapping.get("columns") or []
                            if str(column.get("sheet_name") or "") == sheet_name
                        ],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    facts_json=json.dumps(facts, ensure_ascii=False, indent=2),
                ),
            ),
        ],
        max_tokens=_FILL_BATCH_MAX_TOKENS,
    )

    result_by_id = {item.item_id: item for item in result.items}
    facts_by_item: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        facts_by_item.setdefault(str(fact.get("item_id") or ""), []).append(fact)

    filled_items = []
    for requested in items:
        item_id = str(requested.get("item_id") or "")
        returned = result_by_id.get(item_id)
        returned_fields = returned.fields if returned is not None else {}
        fields: dict[str, Any] = {}
        for key, field in (requested.get("fields") or {}).items():
            if not isinstance(field, dict):
                continue
            value_type = str(field.get("value_type") or "")
            value = returned_fields.get(key)
            if value_type == "date":
                value = (sheet_periods.get(str(key)) or {}).get("report_date") or value
            fields[str(key)] = _normalize_value(value, value_type)

        allowed_refs = {
            str(fact.get("source_ref") or "")
            for fact in facts_by_item.get(item_id, [])
            if fact.get("source_ref")
        }
        for key, field in (requested.get("fields") or {}).items():
            if not isinstance(field, dict) or field.get("value_type") != "date":
                continue
            source_ref = (sheet_periods.get(str(key)) or {}).get("source_ref")
            if source_ref:
                allowed_refs.add(str(source_ref))

        has_value = any(value not in (None, "") for value in fields.values())
        selected_refs = {
            str(source_ref)
            for source_ref in (
                returned.evidence_refs if returned is not None else []
            )
            if str(source_ref) in allowed_refs
        }
        for key, value in fields.items():
            if value in (None, ""):
                continue
            field = (requested.get("fields") or {}).get(key) or {}
            if field.get("value_type") == "date":
                source_ref = (sheet_periods.get(str(key)) or {}).get("source_ref")
                if source_ref:
                    selected_refs.add(str(source_ref))
                continue
            report_date = (sheet_periods.get(str(key)) or {}).get("report_date")
            for fact in facts_by_item.get(item_id, []):
                if (
                    report_date
                    and fact.get("report_date")
                    and not _same_date(report_date, fact.get("report_date"))
                ):
                    continue
                if _same_value(value, fact.get("value")) and fact.get("source_ref"):
                    selected_refs.add(str(fact["source_ref"]))

        reason = (
            returned.reason_one_line
            if returned is not None and returned.reason_one_line
            else "文件中未发现相关信息"
        )
        filled_items.append(
            {
                "item_id": item_id,
                "fields": fields,
                "confidence": returned.confidence if returned is not None else "low",
                "reason_one_line": reason,
                "evidence_refs": sorted(selected_refs) if has_value else [],
            }
        )
    idx = state.get("batch_index", 0)
    total = state.get("total_batches", 0)
    return {
        "filled_items": filled_items,
        "log_lines": [
            f"已填批次 {idx + 1}/{total}"
            f"（sheet={sheet_name}, items={len(filled_items)}）"
        ],
        "progress": f"正在填表：批次 {idx + 1}/{total}",
    }


_UNMAPPED_NOTE_MARK = "列报告期未映射成功"


def _annotate_unmapped_columns(
    schema: dict[str, Any], period_mapping: dict[str, Any]
) -> None:
    """列没映射上时，空值原因不能写成「文件中未发现相关信息」，要说清是哪一步没走通。"""
    unmapped: dict[str, list[str]] = {}
    for column in period_mapping.get("columns") or []:
        if column.get("report_date"):
            continue
        label = str(column.get("field_key") or "")
        if column.get("column_label"):
            label = f"{label}（{column.get('column_label')}）"
        unmapped.setdefault(str(column.get("sheet_name") or ""), []).append(label)
    if not unmapped:
        return

    for sheet in schema.get("sheets") or []:
        columns = unmapped.get(str(sheet.get("sheet") or sheet.get("name") or ""))
        if not columns:
            continue
        note = (
            "、".join(columns)
            + f"{_UNMAPPED_NOTE_MARK}，该列未参与填报，非源文件缺失"
        )
        for item in sheet.get("items") or []:
            fields = item.get("fields") or {}
            if any(
                isinstance(field, dict) and field.get("value") not in (None, "")
                for field in fields.values()
            ):
                continue
            reason = str(item.get("reason_one_line") or "").strip()
            if _UNMAPPED_NOTE_MARK in reason:
                continue
            item["reason_one_line"] = (f"{reason}；{note}" if reason else note)[:500]


def merge_schema_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    schema = json.loads(
        json.dumps(state.get("fill_schema") or state.get("filled_schema") or {})
    )
    by_id = {it.get("item_id"): it for it in (state.get("filled_items") or [])}

    for sh in schema.get("sheets") or []:
        for item in sh.get("items") or []:
            fid = item.get("item_id")
            upd = by_id.get(fid)
            if not upd:
                continue
            field_vals = upd.get("fields") or {}
            for key, field in (item.get("fields") or {}).items():
                if not isinstance(field, dict):
                    continue
                if key in field_vals:
                    val = field_vals[key]
                    # Allow {value: ...} or raw
                    if isinstance(val, dict) and "value" in val:
                        field["value"] = val.get("value")
                    else:
                        field["value"] = val
            if upd.get("confidence") is not None:
                item["confidence"] = upd.get("confidence")
            if upd.get("reason_one_line") is not None:
                item["reason_one_line"] = upd.get("reason_one_line")
            if upd.get("evidence_refs") is not None:
                item["evidence_refs"] = upd.get("evidence_refs")

    _annotate_unmapped_columns(schema, state.get("period_mapping") or {})

    write_json(root / "outputs" / "case2_filled_schema.json", schema)

    # notes
    lines = ["# Case2 填报说明", ""]
    for sh in schema.get("sheets") or []:
        lines.append(f"## {sh.get('sheet')}")
        for item in sh.get("items") or []:
            vals = []
            for k, f in (item.get("fields") or {}).items():
                if isinstance(f, dict) and f.get("value") not in (None, ""):
                    vals.append(f"{k}={f.get('value')}")
            if vals or item.get("reason_one_line"):
                lines.append(
                    f"- {item.get('item_id')} {item.get('label')}: "
                    f"{', '.join(vals)} | {item.get('reason_one_line') or ''}"
                )
        lines.append("")
    (root / "outputs" / "collection_fill_notes.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    return {
        "filled_schema": schema,
        "log_lines": ["已合并写入 case2_filled_schema.json"],
        "progress": "fill_plan 合并完成",
    }

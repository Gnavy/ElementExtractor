from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.llm import structured_llm
from app.agents.prompts import case2 as prompts
from app.agents.schemas.case2_item import Case2BatchFill
from app.agents.tools.context import collect_ocr_snippets, write_json


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


def fill_one_batch_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    items = state.get("items") or []
    sheet_name = state.get("sheet_name") or ""
    labels = [str(it.get("label") or "") for it in items]
    context = state.get("context_snippets") or collect_ocr_snippets(
        root,
        keywords=[w for w in labels if w][:10],
        max_files=12,
        max_total_chars=16000,
    )
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

    llm = structured_llm(Case2BatchFill)
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
                    context=context,
                ),
            ),
        ]
    )

    filled_items = []
    for item in result.items:
        filled_items.append(
            {
                "item_id": item.item_id,
                "fields": item.fields or {},
                "confidence": item.confidence,
                "reason_one_line": item.reason_one_line,
                "evidence_refs": item.evidence_refs or [],
            }
        )
    idx = state.get("batch_index", 0)
    total = state.get("total_batches", 0)
    return {
        "filled_items": filled_items,
        "log_lines": [f"已填批次 {idx + 1}/{total}（sheet={sheet_name}, items={len(filled_items)}）"],
        "progress": f"正在填表：批次 {idx + 1}/{total}",
    }


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

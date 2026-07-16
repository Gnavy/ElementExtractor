from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.llm import structured_llm
from app.agents.prompts import case1 as prompts
from app.agents.schemas.case1_row import Case1GroupFill
from app.agents.tools.context import collect_ocr_snippets


def fill_one_group_node(state: dict[str, Any]) -> dict[str, Any]:
    """Send worker: fill a single indicator_group."""
    root = Path(state["extract_root"])
    group = state.get("group") or {}
    task_id = state.get("task_id") or ""
    region = state.get("region") or ""
    user_rules = state.get("user_rules") or "（无额外用户规则）"
    tavily_md = state.get("tavily_md") or "（无）"
    name = group.get("indicator_name") or ""
    keywords = [name] + [
        (r.get("option_text") or "")[:20]
        for r in (group.get("rows") or [])[:6]
    ]
    context = state.get("context_snippets") or collect_ocr_snippets(
        root,
        keywords=[k for k in keywords if k],
        max_files=10,
        max_total_chars=14000,
    )

    rows_json = json.dumps(group.get("rows") or [], ensure_ascii=False, indent=2)
    llm = structured_llm(Case1GroupFill)
    result: Case1GroupFill = llm.invoke(
        [
            ("system", prompts.FILL_GROUP_SYSTEM),
            (
                "human",
                prompts.FILL_GROUP_USER.format(
                    task_id=task_id,
                    region=region or "未知",
                    user_rules=user_rules[:4000],
                    indicator_name=name,
                    indicator_explanation=group.get("indicator_explanation") or "",
                    choice_mode=group.get("choice_mode") or "unknown",
                    allowed_choices=json.dumps(
                        group.get("allowed_choices") or [], ensure_ascii=False
                    ),
                    data_source_priority=group.get("data_source_priority") or "",
                    requires_tavily=bool(group.get("requires_tavily_search")),
                    tavily_hint=group.get("tavily_query_hint") or "",
                    rows_json=rows_json,
                    tavily_md=tavily_md[:5000],
                    context=context,
                ),
            ),
        ]
    )

    sheet_name = group.get("_sheet") or ""
    fills = []
    for row in result.rows:
        fills.append(
            {
                "indicator_name": name,
                "choice_mode": group.get("choice_mode"),
                "sheet": sheet_name,
                "row": row.row,
                "choice": row.choice,
                "remark": row.remark or "",
                "evidence_refs": row.evidence_refs or [],
            }
        )
    # Ensure all catalog rows appear (empty if LLM omitted)
    seen = {f["row"] for f in fills}
    for r in group.get("rows") or []:
        rn = r.get("row")
        if rn is not None and rn not in seen:
            fills.append(
                {
                    "indicator_name": name,
                    "choice_mode": group.get("choice_mode"),
                    "sheet": sheet_name,
                    "row": rn,
                    "choice": None,
                    "remark": "",
                    "evidence_refs": [],
                }
            )

    idx = state.get("group_index", 0)
    total = state.get("total_groups", 0)
    return {
        "row_fills": fills,
        "log_lines": [f"已填指标组 ({idx + 1}/{total}): {name}"],
        "progress": f"正在填表：指标组 {idx + 1}/{total}",
    }

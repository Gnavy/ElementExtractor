from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agents.llm import guard_config, output_cap, structured_llm
from app.agents.prompts import case1 as prompts
from app.agents.schemas.case1_row import Case1GroupFill
from app.agents.schemas.coerce import coerce_json_list
from app.agents.tools.context import collect_ocr_snippets
from app.services.case1_retry_hints import previous_issues_for_group


# 单个指标组的输出上限。实测最大一组正常输出约 1862 字（≈2000 token），留 4 倍余量。
# 没有上限时模型可在 JSON 字符串里失控生成——2026-07-30 任务 19226215 的
# 「周边配套分析」连续两轮生成到 19.8 万字符仍未闭合 JSON，整个任务因此 FAILED。
_FILL_GROUP_MAX_TOKENS = 8192

def _empty_fills(group: dict[str, Any], name: str, sheet_name: str) -> list[dict[str, Any]]:
    fills = []
    for r in group.get("rows") or []:
        rn = r.get("row")
        if rn is None:
            continue
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
    return fills


def _invoke_group_fill(llm: Any, messages: list) -> Case1GroupFill:
    try:
        return llm.invoke(messages, config=guard_config(), **output_cap(_FILL_GROUP_MAX_TOKENS))
    except ValidationError as exc:
        # 部分模型把 rows 整段塞成字符串；尝试从异常输入中手工解析
        for err in exc.errors():
            if err.get("loc") == ("rows",) and isinstance(err.get("input"), str):
                raw = {"rows": coerce_json_list(err["input"])}
                return Case1GroupFill.model_validate(raw)
        raise


def fill_one_group_node(state: dict[str, Any]) -> dict[str, Any]:
    """Send worker: fill a single indicator_group."""
    root = Path(state["extract_root"])
    group = state.get("group") or {}
    task_id = state.get("task_id") or ""
    region = state.get("region") or ""
    user_rules = state.get("user_rules") or "（无额外用户规则）"
    tavily_md = state.get("tavily_md") or "（无）"
    name = group.get("indicator_name") or ""
    explanation = group.get("indicator_explanation") or ""
    data_src = group.get("data_source_priority") or ""
    sheet_name = group.get("_sheet") or ""
    keywords = [
        name,
        explanation,
        data_src,
        "尽调",
        "可研",
    ]
    for r in group.get("rows") or []:
        opt = (r.get("option_text") or "").strip()
        if opt:
            keywords.append(opt[:48])
            # 去掉序号/方框后的核心短语，提高命中
            core = opt.lstrip("□☑✓ ").strip()
            if core[:2].isdigit() and "." in core[:4]:
                core = core.split(".", 1)[-1].strip()
            if len(core) >= 4:
                keywords.append(core[:24])
    context = state.get("context_snippets") or collect_ocr_snippets(
        root,
        keywords=[k for k in keywords if k and str(k).strip()],
        max_files=18,
        max_chars_per_file=5500,
        max_total_chars=32000,
    )

    rows_json = json.dumps(group.get("rows") or [], ensure_ascii=False, indent=2)
    llm = structured_llm(Case1GroupFill)
    messages = [
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
                retry_hints=previous_issues_for_group(root, name),
                tavily_md=tavily_md[:5000],
                context=context,
            ),
        ),
    ]

    try:
        result = _invoke_group_fill(llm, messages)
    except Exception as exc:  # noqa: BLE001
        # 单组失败不拖垮整图；留空交由校验轮重试
        return {
            "row_fills": _empty_fills(group, name, sheet_name),
            "errors": [f"fill_group「{name}」解析失败: {exc}"],
            "log_lines": [f"填表失败（待修复轮重试）: {name}"],
            "progress": f"正在填表：指标组失败 {name}",
        }

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

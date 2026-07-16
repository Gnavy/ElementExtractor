"""Case1 due-diligence indicator fill LangGraph."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.nodes.case1.fill_group import fill_one_group_node
from app.agents.nodes.case1.index_materials import index_materials_node
from app.agents.nodes.case1.parse_template import parse_template_node
from app.agents.nodes.case1.region_tavily import resolve_region_node, tavily_batch_node
from app.agents.nodes.case1.validate_fix import mark_fix_round_node, validate_case1_node
from app.agents.nodes.case1.write_xlsx import write_xlsx_node
from app.agents.nodes.common.load_meta import load_meta_node
from app.agents.state import Case1State


def _user_rules_from_state(state: Case1State) -> str:
    meta = state.get("meta") or {}
    rules = (meta.get("indicator_judgment_rules") or "").strip()
    if rules:
        return rules
    root = state.get("extract_root") or ""
    path = f"{root}/inputs/indicator_judgment_rules.md"
    try:
        with open(path, encoding="utf-8") as fp:
            return fp.read()
    except OSError:
        return ""


def _fanout_groups(state: Case1State) -> list[Send] | Literal["write_xlsx"]:
    groups = state.get("indicator_groups") or []
    retry_names = set(state.get("groups_to_retry") or [])
    if retry_names:
        groups = [g for g in groups if (g.get("indicator_name") or "") in retry_names]
    if not groups:
        return "write_xlsx"

    tavily = state.get("tavily_results") or {}
    user_rules = _user_rules_from_state(state)
    region = state.get("region") or ""
    total = len(groups)
    sends: list[Send] = []
    for i, grp in enumerate(groups):
        name = grp.get("indicator_name") or ""
        tv = tavily.get(name) or {}
        sends.append(
            Send(
                "fill_group",
                {
                    "task_id": state.get("task_id") or "",
                    "extract_root": state.get("extract_root") or "",
                    "group": grp,
                    "group_index": i,
                    "total_groups": total,
                    "region": region,
                    "tavily_md": tv.get("text") or "",
                    "user_rules": user_rules,
                    "context_snippets": "",
                },
            )
        )
    return sends


def _route_after_validate(
    state: Case1State,
) -> Literal["fix_round", "__end__"]:
    if state.get("validation_ok"):
        return "__end__"
    rnd = int(state.get("fix_round") or 0)
    retries = state.get("groups_to_retry") or []
    if rnd < 2 and retries:
        return "fix_round"
    return "__end__"


def build_case1_graph(checkpointer=None):
    g = StateGraph(Case1State)
    g.add_node("load_meta", load_meta_node)
    g.add_node("parse_template", parse_template_node)
    g.add_node("index_materials", index_materials_node)
    g.add_node("resolve_region", resolve_region_node)
    g.add_node("tavily_batch", tavily_batch_node)
    g.add_node("fill_group", fill_one_group_node)
    g.add_node("write_xlsx", write_xlsx_node)
    g.add_node("validate", validate_case1_node)
    g.add_node("fix_round", mark_fix_round_node)

    g.add_edge(START, "load_meta")
    g.add_edge("load_meta", "parse_template")
    g.add_edge("parse_template", "index_materials")
    g.add_edge("index_materials", "resolve_region")
    g.add_edge("resolve_region", "tavily_batch")
    g.add_conditional_edges(
        "tavily_batch",
        _fanout_groups,
        ["fill_group", "write_xlsx"],
    )
    g.add_edge("fill_group", "write_xlsx")
    g.add_edge("write_xlsx", "validate")
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"fix_round": "fix_round", "__end__": END},
    )
    g.add_conditional_edges(
        "fix_round",
        _fanout_groups,
        ["fill_group", "write_xlsx"],
    )

    return g.compile(checkpointer=checkpointer)

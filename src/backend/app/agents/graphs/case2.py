"""Case2 fill_plan LangGraph."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.nodes.case2.dump_schema import dump_schema_node
from app.agents.nodes.case2.evidence import (
    build_period_map_node,
    extract_evidence_chunk_node,
    merge_evidence_node,
    prepare_evidence_chunks_node,
)
from app.agents.nodes.case2.fill_items import (
    fill_one_batch_node,
    merge_schema_node,
    prepare_batches_node,
)
from app.agents.nodes.case2.postprocess import (
    apply_calc_node,
    backfill_node,
    find_retry_items_node,
)
from app.agents.nodes.common.load_meta import load_meta_node
from app.agents.state import Case2State


def _fanout_evidence_chunks(
    state: Case2State,
) -> list[Send] | Literal["merge_evidence"]:
    chunks = state.get("material_chunks") or []
    if not chunks:
        return "merge_evidence"
    total = len(chunks)
    return [
        Send(
            "extract_evidence",
            {
                "task_id": state.get("task_id") or "",
                "material_chunk": chunk,
                "evidence_targets": chunk.get("targets")
                or state.get("evidence_targets")
                or [],
                "chunk_index": index,
                "total_chunks": total,
            },
        )
        for index, chunk in enumerate(chunks)
    ]


def _fanout_batches(state: Case2State) -> list[Send] | Literal["merge_schema"]:
    batches = state.get("item_batches") or []
    if not batches:
        return "merge_schema"
    total = len(batches)
    sends: list[Send] = []
    for i, batch in enumerate(batches):
        sends.append(
            Send(
                "fill_batch",
                {
                    "task_id": state.get("task_id") or "",
                    "extract_root": state.get("extract_root") or "",
                    "sheet_name": batch.get("sheet_name") or "",
                    "items": batch.get("items") or [],
                    "column_headers": batch.get("column_headers") or {},
                    "user_rules": state.get("user_rules") or "",
                    "evidence_catalog": state.get("evidence_catalog") or {},
                    "period_mapping": state.get("period_mapping") or {},
                    "batch_index": i,
                    "total_batches": total,
                },
            )
        )
    return sends


def _route_after_retry_check(
    state: Case2State,
) -> Literal["prepare_batches", "apply_calc"]:
    if state.get("items_to_retry"):
        return "prepare_batches"
    return "apply_calc"


def build_case2_graph(checkpointer=None):
    g = StateGraph(Case2State)
    g.add_node("load_meta", load_meta_node)
    g.add_node("dump_schema", dump_schema_node)
    g.add_node("prepare_evidence", prepare_evidence_chunks_node)
    g.add_node("extract_evidence", extract_evidence_chunk_node)
    g.add_node("merge_evidence", merge_evidence_node)
    g.add_node("map_periods", build_period_map_node)
    g.add_node("prepare_batches", prepare_batches_node)
    g.add_node("fill_batch", fill_one_batch_node)
    g.add_node("merge_schema", merge_schema_node)
    g.add_node("find_retry", find_retry_items_node)
    g.add_node("apply_calc", apply_calc_node)
    g.add_node("backfill", backfill_node)

    g.add_edge(START, "load_meta")
    g.add_edge("load_meta", "dump_schema")
    g.add_edge("dump_schema", "prepare_evidence")
    g.add_conditional_edges(
        "prepare_evidence",
        _fanout_evidence_chunks,
        ["extract_evidence", "merge_evidence"],
    )
    g.add_edge("extract_evidence", "merge_evidence")
    g.add_edge("merge_evidence", "map_periods")
    g.add_edge("map_periods", "prepare_batches")
    g.add_conditional_edges(
        "prepare_batches",
        _fanout_batches,
        ["fill_batch", "merge_schema"],
    )
    g.add_edge("fill_batch", "merge_schema")
    g.add_edge("merge_schema", "find_retry")
    g.add_conditional_edges(
        "find_retry",
        _route_after_retry_check,
        {"prepare_batches": "prepare_batches", "apply_calc": "apply_calc"},
    )
    g.add_edge("apply_calc", "backfill")
    g.add_edge("backfill", END)

    return g.compile(checkpointer=checkpointer)

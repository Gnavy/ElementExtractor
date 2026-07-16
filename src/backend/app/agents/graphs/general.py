"""General / classification / extraction LangGraph."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.nodes.common.load_meta import load_meta_node
from app.agents.nodes.general.classify import classify_node
from app.agents.nodes.general.collection_fill import (
    collection_fill_node,
    maybe_mark_collection_node,
)
from app.agents.nodes.general.crop import crop_images_node
from app.agents.nodes.general.extract import (
    extract_one_field_node,
    merge_extracted_node,
    prepare_fields_node,
)
from app.agents.nodes.general.inventory import inventory_files_node
from app.agents.nodes.general.validate import validate_outputs_node
from app.agents.state import GeneralState


def _route_after_classify(
    state: GeneralState,
) -> Literal["prepare_fields", "validate"]:
    kind = state.get("task_kind") or "general"
    if kind == "classification":
        return "validate"
    return "prepare_fields"


def _fanout_fields(state: GeneralState) -> list[Send] | Literal["merge_extracted"]:
    fields = state.get("schema_fields") or []
    if not fields:
        return "merge_extracted"
    cls = state.get("classification") or {}
    labels = [c.get("label", "") for c in (cls.get("categories") or [])]
    summary = "、".join(labels) if labels else "（无分类或仅抽取）"
    shared = state.get("material_context") or ""
    sends: list[Send] = []
    for field in fields:
        sends.append(
            Send(
                "extract_field",
                {
                    "task_id": state.get("task_id") or "",
                    "extract_root": state.get("extract_root") or "",
                    "field": field,
                    "classification_summary": summary,
                    "context_snippets": shared,
                    "retry_count": 0,
                },
            )
        )
    return sends


def _route_after_mark(state: GeneralState) -> Literal["collection_fill", "validate"]:
    if state.get("need_collection_fill"):
        return "collection_fill"
    return "validate"


def build_general_graph(checkpointer=None):
    g = StateGraph(GeneralState)
    g.add_node("load_meta", load_meta_node)
    g.add_node("inventory", inventory_files_node)
    g.add_node("classify", classify_node)
    g.add_node("prepare_fields", prepare_fields_node)
    g.add_node("extract_field", extract_one_field_node)
    g.add_node("merge_extracted", merge_extracted_node)
    g.add_node("crop_images", crop_images_node)
    g.add_node("mark_collection", maybe_mark_collection_node)
    g.add_node("collection_fill", collection_fill_node)
    g.add_node("validate", validate_outputs_node)

    g.add_edge(START, "load_meta")
    g.add_edge("load_meta", "inventory")

    # inventory -> classify (or prepare_fields for extraction-only)
    g.add_conditional_edges(
        "inventory",
        lambda s: (
            "prepare_fields"
            if (s.get("task_kind") == "extraction")
            else "classify"
        ),
        {"classify": "classify", "prepare_fields": "prepare_fields"},
    )

    g.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "prepare_fields": "prepare_fields",
            "validate": "validate",
        },
    )

    g.add_conditional_edges(
        "prepare_fields",
        _fanout_fields,
        ["extract_field", "merge_extracted"],
    )
    g.add_edge("extract_field", "merge_extracted")
    g.add_edge("merge_extracted", "crop_images")
    g.add_edge("crop_images", "mark_collection")
    g.add_conditional_edges(
        "mark_collection",
        _route_after_mark,
        {"collection_fill": "collection_fill", "validate": "validate"},
    )
    g.add_edge("collection_fill", "validate")
    g.add_edge("validate", END)

    return g.compile(checkpointer=checkpointer)

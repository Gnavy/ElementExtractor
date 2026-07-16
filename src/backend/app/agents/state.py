"""Shared LangGraph state types."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from typing_extensions import TypedDict


def _merge_dicts(left: dict, right: dict) -> dict:
    out = dict(left or {})
    out.update(right or {})
    return out


def _append_list(left: list, right: list) -> list:
    return list(left or []) + list(right or [])


def _last_value(left: Any, right: Any) -> Any:
    """Reducer for parallel nodes writing the same scalar channel."""
    return right if right is not None else left


class BaseAgentState(TypedDict, total=False):
    task_id: str
    task_kind: str
    extract_root: str
    meta: dict[str, Any]
    log_lines: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    # 并行 Send 节点会同时写 progress，必须用 reducer
    progress: Annotated[str, _last_value]
    validation_ok: Annotated[bool, _last_value]
    validation_msg: Annotated[str, _last_value]
    fix_round: Annotated[int, _last_value]


class GeneralState(BaseAgentState, total=False):
    file_inventory: list[str]
    classification: dict[str, Any]
    schema_fields: list[dict[str, Any]]
    extracted_fields: Annotated[dict[str, Any], _merge_dicts]
    fields_to_retry: list[str]
    collection_template_path: Optional[str]
    need_collection_fill: bool
    outputs_ready: bool
    material_context: str


class FieldExtractState(TypedDict, total=False):
    """Payload for Send() field extraction workers."""

    task_id: str
    extract_root: str
    field: dict[str, Any]
    classification_summary: str
    context_snippets: str
    retry_count: int


class Case1State(BaseAgentState, total=False):
    catalog: dict[str, Any]
    indicator_groups: list[dict[str, Any]]
    region: Annotated[str, _last_value]
    tavily_results: Annotated[dict[str, Any], _merge_dicts]
    row_fills: Annotated[list[dict[str, Any]], _append_list]
    groups_to_retry: Annotated[list[str], _last_value]
    material_index: dict[str, Any]
    catalog_path: str
    filled_path: Annotated[str, _last_value]


class Case1GroupState(TypedDict, total=False):
    """Payload for Send() indicator-group workers."""

    task_id: str
    extract_root: str
    group: dict[str, Any]
    group_index: int
    total_groups: int
    region: str
    tavily_md: str
    user_rules: str
    context_snippets: str


class Case2State(BaseAgentState, total=False):
    fill_schema: dict[str, Any]
    filled_schema: Annotated[dict[str, Any], _last_value]
    item_batches: list[list[dict[str, Any]]]
    filled_items: Annotated[list[dict[str, Any]], _append_list]
    items_to_retry: Annotated[list[str], _last_value]
    user_rules: str
    backfill_ok: Annotated[bool, _last_value]
    backfill_msg: Annotated[str, _last_value]


class Case2BatchState(TypedDict, total=False):
    """Payload for Send() item-batch workers."""

    task_id: str
    extract_root: str
    sheet_name: str
    items: list[dict[str, Any]]
    column_headers: dict[str, Any]
    user_rules: str
    context_snippets: str
    batch_index: int
    total_batches: int

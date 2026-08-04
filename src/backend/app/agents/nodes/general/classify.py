from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.llm import structured_llm
from app.agents.prompts import general as prompts
from app.agents.schemas.classification import ClassificationResult
from app.agents.tools.context import collect_ocr_snippets, write_json
from app.agents.tools.path_remap import remap_classification_payload


def classify_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    meta = state.get("meta") or {}
    task_id = state.get("task_id") or meta.get("task_id") or ""
    basis = meta.get("classification_basis") or "按业务常规目录分类"
    files = state.get("file_inventory") or []
    file_list = "\n".join(f"- {p}" for p in files[:300]) or "（无文件）"
    context = collect_ocr_snippets(root, max_files=8, max_total_chars=12000)

    llm = structured_llm(ClassificationResult, scene="general")
    result: ClassificationResult = llm.invoke(
        [
            ("system", prompts.CLASSIFY_SYSTEM),
            (
                "human",
                prompts.CLASSIFY_USER.format(
                    task_id=task_id,
                    classification_basis=basis,
                    file_list=file_list,
                    context=context,
                ),
            ),
        ]
    )
    payload = result.model_dump()
    payload["task_id"] = task_id
    payload = remap_classification_payload(payload, root)
    out_path = root / "outputs" / "classification.json"
    write_json(out_path, payload)

    summary_parts = [c["label"] for c in payload.get("categories") or []]
    return {
        "classification": payload,
        "log_lines": [
            f"已写入 classification.json（类别数={len(summary_parts)}）"
        ],
        "progress": "材料分类完成",
    }


def parse_extract_schema(meta: dict) -> list[dict[str, Any]]:
    raw = meta.get("extract_schema") or "{}"
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, list):
        return []
    return [f for f in fields if isinstance(f, dict) and f.get("name")]

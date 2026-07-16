from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_meta_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    meta_path = root / ".task-meta.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    task_kind = state.get("task_kind") or meta.get("task_kind") or "general"
    return {
        "meta": meta,
        "task_kind": task_kind,
        "task_id": state.get("task_id") or meta.get("task_id") or "",
        "log_lines": [f"已加载 .task-meta.json（task_kind={task_kind}）"],
        "progress": "已加载任务元数据",
    }

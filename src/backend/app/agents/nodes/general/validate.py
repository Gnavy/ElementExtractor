from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_outputs_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    kind = state.get("task_kind") or "general"
    outputs = root / "outputs"
    errors: list[str] = []

    def _ok_json(name: str) -> bool:
        p = outputs / name
        if not p.is_file():
            errors.append(f"缺少 outputs/{name}")
            return False
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{name} JSON 无效: {exc}")
            return False
        return True

    if kind == "classification":
        ready = _ok_json("classification.json")
    elif kind == "extraction":
        ready = _ok_json("extracted.json")
    else:
        ready = _ok_json("classification.json") and _ok_json("extracted.json")
        meta = state.get("meta") or {}
        if meta.get("collection_template_path"):
            filled = outputs / "collection_filled.xlsx"
            if not filled.is_file() or filled.stat().st_size < 512:
                errors.append("缺少有效的 collection_filled.xlsx")
                ready = False

    return {
        "outputs_ready": ready,
        "validation_ok": ready,
        "validation_msg": "OK" if ready else "; ".join(errors),
        "errors": errors,
        "log_lines": [
            "产物校验通过" if ready else f"产物校验失败: {'; '.join(errors)}"
        ],
        "progress": "产物校验完成",
    }

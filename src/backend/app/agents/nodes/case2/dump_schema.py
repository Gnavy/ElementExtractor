from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tools.context import load_json
from app.services.case2_schema_pipeline import dump_case2_fill_schema


def dump_schema_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = dump_case2_fill_schema(root)
    if not ok:
        return {
            "errors": [f"Case2 schema 导出失败: {log}"],
            "log_lines": [f"dump_schema 失败: {log[:300]}"],
        }
    schema = load_json(root / "outputs" / "case2_fill_schema.json", default={})
    meta = state.get("meta") or {}
    user_rules = (meta.get("fill_logic_rules") or "").strip()
    rules_path = root / "inputs" / "fill_logic_rules.md"
    if not user_rules and rules_path.is_file():
        user_rules = rules_path.read_text(encoding="utf-8")
    return {
        "fill_schema": schema,
        "filled_schema": schema,  # start from fill_plan
        "user_rules": user_rules,
        "log_lines": ["已导出 case2_fill_schema.json"],
        "progress": "已导出 fill_plan",
    }

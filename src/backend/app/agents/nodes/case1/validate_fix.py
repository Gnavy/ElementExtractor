from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.tools.script_runner import run_tool_script


def validate_case1_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = run_tool_script(
        root,
        "validate_collection_filled.py",
        [
            "--catalog",
            "outputs/template_row_catalog.json",
            "--filled",
            "outputs/collection_filled.xlsx",
        ],
        timeout=120,
    )
    import re

    report_path = root / "outputs" / "validation_report.json"
    groups_to_retry: list[str] = []
    msg = log[-500:]
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            violations = report.get("violations") or report.get("errors") or []
            for v in violations:
                if isinstance(v, dict):
                    name = v.get("indicator_name") or v.get("group") or ""
                    if name and name not in groups_to_retry:
                        groups_to_retry.append(str(name))
                elif isinstance(v, str):
                    # e.g. 互斥组「增信措施」未选择… / 行10「xxx」…
                    for m in re.findall(r"「([^」]+)」", v):
                        if m not in groups_to_retry:
                            groups_to_retry.append(m)
            msg = (
                f"errors={len(report.get('errors') or [])}, "
                f"warnings={len(report.get('warnings') or [])}"
            )
            if report.get("ok") is True or report.get("passed") is True:
                ok = True
                groups_to_retry = []
            elif report.get("ok") is False:
                ok = False
        except (json.JSONDecodeError, OSError):
            pass

    fix_round = int(state.get("fix_round") or 0)
    return {
        "validation_ok": ok,
        "validation_msg": msg,
        "groups_to_retry": groups_to_retry if not ok else [],
        "fix_round": fix_round,
        "log_lines": [
            "Case1 校验通过" if ok else f"Case1 校验未通过（待修复组={len(groups_to_retry)}）"
        ],
        "progress": "指标表校验完成",
    }


def mark_fix_round_node(state: dict[str, Any]) -> dict[str, Any]:
    rnd = int(state.get("fix_round") or 0) + 1
    return {
        "fix_round": rnd,
        "log_lines": [f"进入第 {rnd} 轮违规组修复"],
        "progress": f"修复轮次 {rnd}",
    }

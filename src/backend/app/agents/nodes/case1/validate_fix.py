from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agents.tools.script_runner import run_tool_script


def _names_from_messages(messages: list) -> list[str]:
    names: list[str] = []
    for v in messages:
        text = ""
        if isinstance(v, dict):
            text = str(v.get("indicator_name") or v.get("group") or v)
        else:
            text = str(v)
        for m in re.findall(r"「([^」]+)」", text):
            if m and m not in names:
                names.append(m)
        # dict 直接带了名字
        if isinstance(v, dict):
            name = v.get("indicator_name") or v.get("group") or ""
            if name and str(name) not in names:
                names.append(str(name))
    return names


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

    report_path = root / "outputs" / "validation_report.json"
    groups_to_retry: list[str] = []
    citation_retry: list[str] = []
    msg = log[-500:]
    passed = False
    fix_round = int(state.get("fix_round") or 0)

    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            errors = report.get("violations") or report.get("errors") or []
            warnings = report.get("warnings") or []
            groups_to_retry = _names_from_messages(errors)
            citation_msgs = [
                w
                for w in warnings
                if "缺少源文件名与原文引用" in str(w)
            ]
            citation_retry = _names_from_messages(citation_msgs)
            msg = f"errors={len(errors)}, warnings={len(warnings)}"
            passed = bool(report.get("ok") is True or report.get("passed") is True)
            if report.get("ok") is False or (errors and not passed):
                passed = False
            ok = passed
        except (json.JSONDecodeError, OSError):
            pass

    # 硬错误优先；无硬错误但备注缺引用时，在修复轮次内继续重填
    if not passed:
        for name in citation_retry:
            if name not in groups_to_retry:
                groups_to_retry.append(name)
        ok = False
    elif citation_retry and fix_round < 2:
        groups_to_retry = citation_retry
        ok = False
        msg = (msg or "") + f"；备注缺引用待修复组={len(citation_retry)}"
    else:
        groups_to_retry = []
        ok = True

    return {
        "validation_ok": ok,
        "validation_msg": msg,
        "groups_to_retry": groups_to_retry if not ok else [],
        "fix_round": fix_round,
        "log_lines": [
            "Case1 校验通过"
            if ok
            else f"Case1 校验未通过（待修复组={len(groups_to_retry)}）"
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

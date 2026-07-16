from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.tools.script_runner import run_tool_script


def parse_template_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    ok, log = run_tool_script(
        root,
        "dump_collection_template.py",
        [
            "--src",
            "inputs/collection_template.xlsx",
            "--out",
            "outputs/template_row_catalog.json",
        ],
        timeout=120,
    )
    if not ok:
        return {
            "errors": [f"模板解析失败: {log}"],
            "log_lines": [f"parse_template 失败: {log[:300]}"],
        }
    run_tool_script(
        root,
        "dump_sheet_headers.py",
        ["--src", "inputs/collection_template.xlsx", "--formulas"],
        timeout=60,
    )
    catalog_path = root / "outputs" / "template_row_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    groups: list[dict[str, Any]] = []
    for sheet in catalog.get("sheets") or []:
        sheet_name = sheet.get("name") or ""
        for section in sheet.get("sections") or []:
            sec_title = section.get("section_title") or ""
            for grp in section.get("indicator_groups") or []:
                g = dict(grp)
                g["_sheet"] = sheet_name
                g["_section"] = sec_title
                groups.append(g)
    if not groups and catalog.get("indicator_groups"):
        groups = list(catalog["indicator_groups"])

    return {
        "catalog": catalog,
        "indicator_groups": groups,
        "catalog_path": "outputs/template_row_catalog.json",
        "log_lines": [f"模板解析完成：指标组={len(groups)}"],
        "progress": f"已解析模板（{len(groups)} 个指标组）",
    }

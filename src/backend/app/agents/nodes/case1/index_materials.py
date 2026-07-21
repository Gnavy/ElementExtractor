from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tools.script_runner import run_tool_script


def index_materials_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    logs: list[str] = []
    ok_body, log_body = run_tool_script(
        root,
        "extract_docx_text.py",
        ["--src", ".", "--out", "outputs/docx_text_index.json"],
        timeout=300,
    )
    logs.append(
        "docx_text_index OK" if ok_body else f"docx body: {log_body[:150]}"
    )
    ok1, log1 = run_tool_script(
        root,
        "extract_docx_comments.py",
        ["--src", ".", "--out", "outputs/docx_comments_index.json"],
        timeout=180,
    )
    logs.append("docx_comments_index OK" if ok1 else f"docx comments: {log1[:150]}")
    ok2, log2 = run_tool_script(
        root,
        "extract_pptx_text.py",
        ["--src", ".", "--out", "outputs/ppt_text_index.json"],
        timeout=180,
    )
    logs.append("ppt_text_index OK" if ok2 else f"ppt index: {log2[:150]}")
    return {
        "material_index": {
            "docx_body": ok_body,
            "docx": ok1,
            "ppt": ok2,
        },
        "log_lines": logs,
        "progress": "材料索引完成",
    }

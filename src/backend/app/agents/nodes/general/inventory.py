from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tools.context import list_material_files
from app.agents.tools.script_runner import run_tool_script


def inventory_files_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    files = list_material_files(root)
    ok, log = run_tool_script(
        root,
        "ocr_inventory.py",
        ["--all-md", "--out", "outputs/ocr_all_md_index.txt"],
        timeout=120,
    )
    notes = [f"材料文件数={len(files)}"]
    if ok:
        notes.append("已生成 outputs/ocr_all_md_index.txt")
    else:
        notes.append(f"ocr_inventory 跳过/失败: {log[:200]}")
    # litigation index (best-effort)
    run_tool_script(
        root,
        "ocr_inventory.py",
        ["--out", "outputs/ocr_litigation_index.txt"],
        timeout=60,
    )
    return {
        "file_inventory": files,
        "log_lines": notes,
        "progress": f"已盘点材料 {len(files)} 个文件",
    }

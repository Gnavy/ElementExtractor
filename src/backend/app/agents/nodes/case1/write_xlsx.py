from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell


def _set_cell(ws, row: int, col: int, value) -> bool:
    cell = ws.cell(row, col)
    if isinstance(cell, MergedCell):
        return False
    if cell.data_type == "f":
        return False
    if isinstance(cell.value, str) and cell.value.startswith("="):
        return False
    cell.value = value
    return True


def write_xlsx_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    template = root / "inputs" / "collection_template.xlsx"
    out = root / "outputs" / "collection_filled.xlsx"
    if not template.is_file():
        return {"errors": ["缺少 inputs/collection_template.xlsx"], "log_lines": ["write_xlsx 失败"]}

    shutil.copy2(template, out)
    fills = state.get("row_fills") or []
    # Prefer last fill for each (sheet, row) if duplicates from retries
    by_key: dict[tuple[str, int], dict] = {}
    for f in fills:
        rn = f.get("row")
        if rn is None:
            continue
        sheet = str(f.get("sheet") or "")
        by_key[(sheet, int(rn))] = f

    wb = load_workbook(out)
    default_sheet = wb.sheetnames[0]
    written_choice = 0
    written_remark = 0
    for (sheet, row), f in by_key.items():
        ws_name = sheet if sheet in wb.sheetnames else default_sheet
        ws = wb[ws_name]
        choice = f.get("choice")
        remark = f.get("remark") or ""
        if choice not in (None, ""):
            if _set_cell(ws, row, 4, choice):  # D
                written_choice += 1
        if remark:
            if _set_cell(ws, row, 5, remark):  # E
                written_remark += 1
    wb.save(out)

    # notes markdown
    lines = [
        "| sheet | row | indicator_name | filled_choice | remark |",
        "|-------|-----|----------------|---------------|--------|",
    ]
    for (sheet, row) in sorted(by_key.keys(), key=lambda x: (x[0], x[1])):
        f = by_key[(sheet, row)]
        choice = f.get("choice") or ""
        remark = (f.get("remark") or "").replace("|", "\\|").replace("\n", " ")
        name = (f.get("indicator_name") or "").replace("|", "\\|")
        lines.append(f"| {sheet or default_sheet} | {row} | {name} | {choice} | {remark} |")
    notes_path = root / "outputs" / "collection_fill_notes.md"
    notes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "filled_path": "outputs/collection_filled.xlsx",
        "log_lines": [
            f"已写入 collection_filled.xlsx（D列={written_choice}, E列={written_remark}）"
        ],
        "progress": "指标表已写入 xlsx",
    }

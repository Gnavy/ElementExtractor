#!/usr/bin/env python3
"""
通用模板目录导出：
- 读取每个 sheet 的可见表头（前若干行）
- 导出可写入单元格与公式单元格
- 输出 outputs/template_row_catalog.json 供 Case2 智能体参考
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _non_empty_row_values(ws, row: int, max_col: int = 12) -> list[str]:
    vals = []
    for c in range(1, max_col + 1):
        v = ws.cell(row, c).value
        vals.append("" if v is None else str(v).strip())
    return vals


def main() -> None:
    p = argparse.ArgumentParser(description="导出通用 xlsx 模板目录")
    p.add_argument("--src", required=True, help="如 inputs/collection_template.xlsx")
    p.add_argument("--out", default="outputs/template_row_catalog.json")
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    if not str(src).startswith(str(cwd)) or not src.is_file():
        raise SystemExit("模板路径无效")

    from openpyxl import load_workbook
    from openpyxl.cell.cell import MergedCell

    wb = load_workbook(src, read_only=False, data_only=False)
    try:
        sheets = []
        for name in wb.sheetnames:
            ws = wb[name]
            max_row = ws.max_row or 0
            max_col = ws.max_column or 0
            preview_rows = []
            for r in range(1, min(20, max_row + 1)):
                vals = _non_empty_row_values(ws, r, max_col=min(max_col, 12))
                if any(v for v in vals):
                    preview_rows.append({"row": r, "values": vals})

            writable_cells = []
            formula_cells = []
            for r in range(1, max_row + 1):
                for c in range(1, max_col + 1):
                    cell = ws.cell(r, c)
                    if isinstance(cell, MergedCell):
                        continue
                    coord = cell.coordinate
                    if cell.data_type == "f" or (
                        isinstance(cell.value, str) and cell.value.startswith("=")
                    ):
                        formula_cells.append(coord)
                    else:
                        writable_cells.append(coord)

            sheets.append(
                {
                    "name": name,
                    "max_row": max_row,
                    "max_col": max_col,
                    "header_preview": preview_rows,
                    "formula_cells": formula_cells,
                    "writable_cells_count": len(writable_cells),
                }
            )
    finally:
        wb.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"source": src.name, "sheets": sheets}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(out.relative_to(cwd).as_posix())


if __name__ == "__main__":
    main()

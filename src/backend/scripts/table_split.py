"""把被并成一张的双栏财务报表拆回两半。

资产负债表常排成左右两栏（左资产、右负债和所有者权益），docling 会把它认成一张表，
并且**少认一列**：左半的最后一个金额列和右半的科目名列被塞进同一格，
例如 `134,715,961.79 短期借款`、`800.955.434.17短期借款`。
模型看到一格两样东西，就会把左半的年初数错记成右半科目的值。

判据取自表头本身：某个表头格里既有期间列名又有别的列名（`年初数 负债和所有者权益`），
说明这一列是两列并的——是表格自己给出的信号，不用坐标也不用模型猜。

拆不开的格（例如一格里有两个金额，说明还发生了跨行错位）不猜：整格原样留在科目名
一侧、金额侧留空，并记进 failures 供人工复核。宁可留空，不可填错。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.case2_amounts import parse_amount  # noqa: E402

# 期间列名：拆表头时用它定位左半列名的结尾
_PERIOD_LABEL = (
    "期末余额|年初余额|期初余额|年末余额|期末数|年初数|期初数|年末数|"
    "本期金额|上期金额|本年累计金额|本月金额|本年金额|上年金额|上年同期金额"
)
_HEADER_LABEL_RE = re.compile(rf"({_PERIOD_LABEL})")
_CJK_RE = re.compile(r"[一-鿿]")
# 金额在前、中文科目名在后；两者之间可以没有空格
_CELL_SPLIT_RE = re.compile(r"^([+-]?[\d][\d.,\s]*?)\s*([一-鿿].*)$")
_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")

# 一列至少这么多行呈现「金额+科目名」才认定它是被并的列
_MIN_GLUED_ROWS = 3
# 表头只在表格前几行里找
_HEADER_SEARCH_ROWS = 3


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.fullmatch(cell) for cell in cells if cell)


def _parse_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_row(cells: list[str], widths: list[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths)]
    return "| " + " | ".join(padded) + " |"


def _split_header_cell(text: str) -> tuple[str, str] | None:
    """表头格里两个列名的先后顺序不固定：既有 `年初数 负债和所有者权益`，
    也有 OCR 把两格交错读成 `负债和所有者 年初数 (或股东)权益`。
    因此不认位置，只把期间列名摘出来当左半，剩下的拼回去当右半。
    """
    match = _HEADER_LABEL_RE.search(text)
    if not match:
        return None
    left = match.group(1)
    right = (text[: match.start()] + text[match.end() :]).strip()
    # 右半必须是另一个列名（含中文），否则 `期末数 05067` 这种脏表头会被误拆
    if not _CJK_RE.search(right):
        return None
    return left, re.sub(r"\s+", "", right)


def _split_data_cell(text: str) -> tuple[str, str] | None:
    match = _CELL_SPLIT_RE.match(text)
    if not match:
        return None
    amount, rest = match.group(1).strip(), match.group(2).strip()
    # 金额侧必须真的解析得出数；`311,266,236.53 20,634,073.53` 这种两个数在此被拒
    if parse_amount(amount) is None:
        return None
    return amount, rest


def _find_glued_column(rows: list[list[str]]) -> tuple[int, int] | None:
    """返回 (表头行号, 被并的列号)；认不出返回 None。"""
    data_rows = [cells for cells in rows if not _is_separator(cells)]
    if len(data_rows) < _MIN_GLUED_ROWS + 1:
        return None
    width = max(len(cells) for cells in rows)

    for header_index, header_cells in enumerate(rows[:_HEADER_SEARCH_ROWS]):
        if _is_separator(header_cells):
            continue
        for column in range(width):
            if column >= len(header_cells):
                continue
            if _split_header_cell(header_cells[column]) is None:
                continue
            hits = sum(
                1
                for cells in rows[header_index + 1 :]
                if not _is_separator(cells)
                and column < len(cells)
                and _split_data_cell(cells[column]) is not None
            )
            if hits >= _MIN_GLUED_ROWS:
                return header_index, column
    return None


def _split_column(
    rows: list[list[str]], header_index: int, column: int
) -> tuple[list[list[str]], list[str]]:
    out: list[list[str]] = []
    failures: list[str] = []
    for index, cells in enumerate(rows):
        if _is_separator(cells):
            out.append(cells + ["---"])
            continue
        padded = list(cells) + [""] * (column + 1 - len(cells))
        text = padded[column]
        if index == header_index:
            pair = _split_header_cell(text)
        elif not text:
            pair = ("", "")
        elif not _CJK_RE.search(text):
            pair = (text, "")  # 只有金额
        elif not any(ch.isdigit() for ch in text):
            pair = ("", text)  # 只有科目名，如「流动负债：」
        else:
            pair = _split_data_cell(text)
            if pair is None:
                # 拆不开：整格留给科目名一侧，金额侧留空，不猜
                failures.append(text)
                pair = ("", text)
        out.append(padded[:column] + [pair[0], pair[1]] + padded[column + 1 :])
    return out, failures


def _table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            if start is None:
                start = index
        elif start is not None:
            blocks.append((start, index))
            start = None
    if start is not None:
        blocks.append((start, len(lines)))
    return blocks


def split_double_column_tables(markdown: str) -> tuple[str, list[dict[str, Any]]]:
    """拆开被并的双栏表；没认出来就原样返回。"""
    lines = markdown.splitlines()
    reports: list[dict[str, Any]] = []
    for start, end in reversed(_table_blocks(lines)):
        rows = [_parse_row(line) for line in lines[start:end]]
        found = _find_glued_column(rows)
        if found is None:
            continue
        header_index, column = found
        split_rows, failures = _split_column(rows, header_index, column)
        width = max(len(cells) for cells in split_rows)
        normalized = [cells + [""] * (width - len(cells)) for cells in split_rows]
        widths = [
            max(len(row[c]) for row in normalized if not _is_separator(row))
            for c in range(width)
        ]
        widths = [max(w, 3) for w in widths]
        rendered = [
            "|" + "|".join("-" * (w + 2) for w in widths) + "|"
            if _is_separator(row)
            else _render_row(row, widths)
            for row in normalized
        ]
        lines[start:end] = rendered
        reports.append(
            {
                "line": start + 1,
                "split_column": column + 1,
                "columns_after": width,
                "unsplittable_cells": failures,
            }
        )
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else ""), list(
        reversed(reports)
    )


def describe(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return "双栏拆分：未发现被并的表"
    total_failed = sum(len(r["unsplittable_cells"]) for r in reports)
    parts = [
        f"第 {r['line']} 行的表拆开第 {r['split_column']} 列 → {r['columns_after']} 列"
        for r in reports
    ]
    suffix = f"；{total_failed} 个格拆不开已留空待人工复核" if total_failed else ""
    return "双栏拆分：" + "，".join(parts) + suffix

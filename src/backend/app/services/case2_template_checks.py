"""按模板自带的核查检验公式核对填报结果，生成复核提示。

只读不回写；仅解析数字/单元格/SUM/加减乘，认不出的公式标「未校验」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_CELL_RE = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$", re.IGNORECASE)
_TOKEN_RE = re.compile(
    r"\s*(?P<tok>[A-Za-z_][A-Za-z0-9_.]*|\$?[A-Z]{1,3}\$?\d+|\d+(?:\.\d+)?|<=|>=|<>|.)",
    re.IGNORECASE,
)
# 模板惯用写法：IF(ABS(<表达式>)<容差,"无误","<哪里有误>")
_TOLERANT_CHECK_RE = re.compile(
    r"^=?\s*IF\s*\(\s*ABS\s*\((?P<expr>.+)\)\s*<\s*(?P<tol>\d+(?:\.\d+)?)\s*,"
    r"\s*(?P<ok>\"[^\"]*\"|'[^']*')\s*,\s*(?P<bad>\"[^\"]*\"|'[^']*')\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ISNUMBER_CHECK_RE = re.compile(
    r"^=?\s*IF\s*\(\s*ISNUMBER\s*\(\s*(?P<ref>\$?[A-Z]{1,3}\$?\d+)\s*\)\s*,"
    r"\s*(?P<ok>\"[^\"]*\"|'[^']*')\s*,\s*(?P<bad>\"[^\"]*\"|'[^']*')\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class TemplateCheck:
    """一条从模板读出来的核查检验。"""

    sheet: str
    cell: str
    kind: str  # tolerant | isnumber | unparsed
    message: str = ""
    expression: str = ""
    tolerance: float = 1.0
    ref: str = ""
    raw: str = ""


@dataclass
class CheckOutcome:
    check: TemplateCheck
    ok: bool | None  # None = 未校验
    delta: float | None = None
    empty_refs: list[str] = field(default_factory=list)
    suggestion: tuple[str, float] | None = None  # (单元格, 由其余项反解出的值)
    delta_matches: list[str] = field(default_factory=list)  # 值恰好等于差额的格
    refs: list[str] = field(default_factory=list)  # 本条公式引用到的全部格
    note: str = ""


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == sep and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            break
        token = match.group("tok")
        pos = match.end()
        if token.strip():
            tokens.append(token)
    return tokens


class _ExprError(ValueError):
    """表达式超出支持范围，调用方应把这条标为未校验。"""


class _Evaluator:
    """极小的表达式求值器：数字 / 单元格 / SUM / 括号 / + - * /。

    刻意只支持这几样。模板里出现别的函数时直接抛错，由调用方降级为
    「未校验」——宁可说不知道，也不要算个似是而非的结果。
    """

    def __init__(self, values: dict[str, float | None], overrides: dict[str, float]):
        self.values = values
        self.overrides = overrides
        self.tokens: list[str] = []
        self.pos = 0
        self.refs: list[str] = []

    def evaluate(self, expression: str) -> float:
        self.tokens = _tokenize(expression)
        self.pos = 0
        value = self._expr()
        if self.pos != len(self.tokens):
            raise _ExprError(f"表达式未解析完: {expression!r}")
        return value

    # --- 递归下降 ---
    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise _ExprError("表达式提前结束")
        self.pos += 1
        return token

    def _expr(self) -> float:
        value = self._term()
        while self._peek() in ("+", "-"):
            op = self._take()
            right = self._term()
            value = value + right if op == "+" else value - right
        return value

    def _term(self) -> float:
        value = self._factor()
        while self._peek() in ("*", "/"):
            op = self._take()
            right = self._factor()
            if op == "*":
                value *= right
            else:
                if right == 0:
                    raise _ExprError("除零")
                value /= right
        return value

    def _factor(self) -> float:
        token = self._peek()
        if token is None:
            raise _ExprError("表达式提前结束")
        if token == "-":
            self._take()
            return -self._factor()
        if token == "+":
            self._take()
            return self._factor()
        if token == "(":
            self._take()
            value = self._expr()
            if self._take() != ")":
                raise _ExprError("括号不匹配")
            return value
        token = self._take()
        if token.upper() == "SUM":
            return self._sum()
        if _CELL_RE.match(token):
            return self._cell(token)
        try:
            return float(token)
        except ValueError as exc:
            raise _ExprError(f"不支持的记号: {token!r}") from exc

    def _sum(self) -> float:
        if self._take() != "(":
            raise _ExprError("SUM 后缺少左括号")
        depth = 1
        raw: list[str] = []
        while True:
            token = self._take()
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    break
            raw.append(token)
        total = 0.0
        for part in _split_top_level(" ".join(raw)):
            total += self._sum_arg(part.strip())
        return total

    def _sum_arg(self, part: str) -> float:
        if ":" in part:
            left, right = [p.strip() for p in part.split(":", 1)]
            return sum(self._cell(coord) for coord in _expand_range(left, right))
        if _CELL_RE.match(part.replace(" ", "")):
            return self._cell(part.replace(" ", ""))
        # SUM 里也可能是子表达式
        sub = _Evaluator(self.values, self.overrides)
        value = sub.evaluate(part)
        self.refs.extend(sub.refs)
        return value

    def _cell(self, coord: str) -> float:
        key = coord.replace("$", "").upper()
        self.refs.append(key)
        if key in self.overrides:
            return self.overrides[key]
        value = self.values.get(key)
        return float(value) if isinstance(value, (int, float)) else 0.0


def _col_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index


def _col_letters(index: int) -> str:
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _expand_range(left: str, right: str) -> Iterable[str]:
    lm = _CELL_RE.match(left.replace("$", ""))
    rm = _CELL_RE.match(right.replace("$", ""))
    if not lm or not rm:
        raise _ExprError(f"无法解析区间: {left}:{right}")
    c1, r1 = _col_index(lm.group(1)), int(lm.group(2))
    c2, r2 = _col_index(rm.group(1)), int(rm.group(2))
    for col in range(min(c1, c2), max(c1, c2) + 1):
        for row in range(min(r1, r2), max(r1, r2) + 1):
            yield f"{_col_letters(col)}{row}"


def _unquote(text: str) -> str:
    return text.strip().strip("\"'").strip()


def read_template_checks(template_path: Path) -> list[TemplateCheck]:
    """把模板里的公式格读成核查检验清单。"""
    from openpyxl import load_workbook

    workbook = load_workbook(template_path, data_only=False)
    checks: list[TemplateCheck] = []
    for sheet_name in workbook.sheetnames:
        worksheet = workbook[sheet_name]
        for row in worksheet.iter_rows():
            for cell in row:
                raw = cell.value
                if not isinstance(raw, str) or not raw.startswith("="):
                    continue
                checks.append(_classify(sheet_name, cell.coordinate, raw))
    workbook.close()
    return checks


def _classify(sheet: str, coord: str, raw: str) -> TemplateCheck:
    tolerant = _TOLERANT_CHECK_RE.match(raw)
    if tolerant:
        return TemplateCheck(
            sheet=sheet,
            cell=coord,
            kind="tolerant",
            message=_unquote(tolerant.group("bad")),
            expression=tolerant.group("expr"),
            tolerance=float(tolerant.group("tol")),
            raw=raw,
        )
    isnumber = _ISNUMBER_CHECK_RE.match(raw)
    if isnumber:
        return TemplateCheck(
            sheet=sheet,
            cell=coord,
            kind="isnumber",
            message=_unquote(isnumber.group("bad")),
            ref=isnumber.group("ref").replace("$", "").upper(),
            raw=raw,
        )
    # 形如 =C4 的镜像格只是把值引过来显示，不是校验，不算「未校验」
    if _CELL_RE.match(raw.lstrip("=").strip()):
        return TemplateCheck(sheet=sheet, cell=coord, kind="mirror", raw=raw)
    return TemplateCheck(sheet=sheet, cell=coord, kind="unparsed", raw=raw)


def _sheet_values(worksheet: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for row in worksheet.iter_rows():
        for cell in row:
            if cell.value is not None:
                values[cell.coordinate.upper()] = cell.value
    return values


def evaluate_checks(
    filled_path: Path, checks: list[TemplateCheck]
) -> list[CheckOutcome]:
    """用回填后的实际值把每条核查算一遍。只读，不改任何单元格。"""
    from openpyxl import load_workbook

    workbook = load_workbook(filled_path, data_only=False)
    outcomes: list[CheckOutcome] = []
    cache: dict[str, dict[str, Any]] = {}
    for check in checks:
        if check.sheet not in workbook.sheetnames:
            outcomes.append(
                CheckOutcome(check, None, note=f"sheet 不存在: {check.sheet}")
            )
            continue
        values = cache.setdefault(check.sheet, _sheet_values(workbook[check.sheet]))
        outcomes.append(_evaluate_one(check, values))
    workbook.close()
    return outcomes


def _numeric(values: dict[str, Any], coord: str) -> float | None:
    value = values.get(coord.upper())
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _evaluate_one(check: TemplateCheck, values: dict[str, Any]) -> CheckOutcome:
    if check.kind == "isnumber":
        value = values.get(check.ref)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not ok:
            from datetime import date, datetime

            ok = isinstance(value, (date, datetime))
        return CheckOutcome(check, bool(ok))

    if check.kind == "mirror":
        return CheckOutcome(check, None, note="镜像取值，非校验公式")

    if check.kind != "tolerant":
        return CheckOutcome(check, None, note="公式形态未支持，已标记为未校验")

    numeric = {k: v for k, v in values.items() if isinstance(v, (int, float))}
    try:
        evaluator = _Evaluator(numeric, {})
        delta = evaluator.evaluate(check.expression)
    except (_ExprError, RecursionError) as exc:
        return CheckOutcome(check, None, note=f"表达式未支持：{exc}")

    refs = sorted(set(evaluator.refs))
    empty = [ref for ref in refs if _numeric(values, ref) is None]
    ok = abs(delta) < check.tolerance
    outcome = CheckOutcome(check, ok, delta=delta, empty_refs=empty, refs=refs)
    if not ok:
        if len(empty) == 1:
            outcome.suggestion = _solve_single_unknown(check, numeric, empty[0], delta)
        outcome.delta_matches = _cells_equal_to_delta(
            numeric, refs, abs(delta), check.tolerance
        )
    return outcome


def _cells_equal_to_delta(
    numeric: dict[str, float],
    refs: list[str],
    delta: float,
    tolerance: float,
) -> list[str]:
    """差额恰好等于某个被引用格的值 → 该格疑似被重复计入或漏计入。

    这不是猜：差额和某一格严丝合缝相等，通常就是那一格多算或少算了一次。
    只给线索，不改数。
    """
    if delta < tolerance:
        return []
    return [
        ref
        for ref in refs
        if ref in numeric and abs(abs(numeric[ref]) - delta) < tolerance
    ]


def _solve_single_unknown(
    check: TemplateCheck,
    numeric: dict[str, float],
    unknown: str,
    delta_at_zero: float,
) -> tuple[str, float] | None:
    """表达式是线性的，代 0 和代 1 各算一次就能反解出唯一空缺项。

    这样不需要按公式形状写死系数，任何线性写法都适用。
    """
    try:
        at_one = _Evaluator(numeric, {unknown: 1.0}).evaluate(check.expression)
    except (_ExprError, RecursionError):
        return None
    coefficient = at_one - delta_at_zero
    if abs(coefficient) < 1e-9:
        return None
    return unknown, -delta_at_zero / coefficient


def check_review_flags(outcomes: list[CheckOutcome]) -> list[dict[str, Any]]:
    """把核查结果转成复核提示。对应 5.2.3。"""
    flags: list[dict[str, Any]] = []
    unparsed = [o for o in outcomes if o.check.kind == "unparsed"]
    for outcome in outcomes:
        check = outcome.check
        if outcome.ok is not False:
            continue
        detail = f"{check.sheet} {check.cell}：{check.message or '核查检验未通过'}"
        if outcome.delta is not None:
            detail += f"，差额 {outcome.delta:,.2f}"
        if outcome.empty_refs:
            detail += f"，其中未填：{'、'.join(outcome.empty_refs)}"
        if outcome.suggestion:
            coord, value = outcome.suggestion
            detail += f"；按本条公式反解 {coord} 应为 {value:,.2f}（未自动写入）"
        if outcome.delta_matches:
            detail += (
                f"；差额恰好等于 {'、'.join(outcome.delta_matches)} 的值，"
                "该格疑似被重复计入或漏计入"
            )
        flags.append(
            {
                "kind": "template_check_failed",
                "sheet_name": check.sheet,
                "cell": check.cell,
                "detail": detail,
            }
        )
    if unparsed:
        flags.append(
            {
                "kind": "template_check_unparsed",
                "detail": (
                    f"{len(unparsed)} 条模板公式超出当前解析范围，未参与校验："
                    + "、".join(f"{o.check.sheet}!{o.check.cell}" for o in unparsed[:8])
                    + "；这些位置的正确性未经核对"
                ),
            }
        )
    return flags


def summarize(outcomes: list[CheckOutcome]) -> dict[str, int]:
    """镜像格不是校验，单独计数，避免把「未校验」数字说大。"""
    real = [o for o in outcomes if o.check.kind != "mirror"]
    return {
        "checks": len(real),
        "passed": sum(1 for o in real if o.ok is True),
        "failed": sum(1 for o in real if o.ok is False),
        "unchecked": sum(1 for o in real if o.ok is None),
        "mirror_cells": len(outcomes) - len(real),
    }

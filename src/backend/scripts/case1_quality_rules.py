#!/usr/bin/env python3
"""Case1 填报内容质量判据。

与 validate_collection_filled.py 的分工：那边是模板结构与取值合法性（罗总基线），
这里只判「填了，但内容不可信」，全部输出 warning 级问题，由调用方决定如何处置。

判据的口径属输出契约（备注只写结论、结论不得与选择相反、每行都要有结论），
但「用什么词、多长算超长、豁免条款怎么写」会随客户模板与模型措辞变化，
因此词表与阈值一律可用环境变量覆盖。下面的默认值仅来自一份材料的实测样本，
不是通用真理：正常备注 136-242 字符 / 0 换行，草稿型备注 899、961 字符 / 14、20 换行。
"""

from __future__ import annotations

import os
import re


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    items = tuple(x.strip() for x in raw.split(",") if x.strip())
    return items or default


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name) or default)
    except ValueError:
        return default
    return v if v > 0 else default


# 被选中行的备注里出现这些说法，等于模型自己说「这项不该选」，与它填的选择相反
SELF_NEGATION_MARKERS = _env_list(
    "CASE1_SELF_NEGATION_MARKERS",
    ("故不选此项", "故不选本项", "因此不选此项", "故未选此项", "不选此项"),
)

# 模型把思考草稿写进备注的标记
# 裸「等等」不作判据——中文里常用作「诸如此类」，会误杀「教育、商业配套等等」
DRAFT_MARKERS = _env_list(
    "CASE1_DRAFT_MARKERS",
    (
        "等等，让我",
        "让我重新",
        "让我再",
        "让我们重新",
        "再次检查材料",
        "重新计算",
        "修正判断",
        "重新核对材料",
    ),
)

REMARK_MAX_LEN = _env_int("CASE1_REMARK_MAX_LEN", 600)
REMARK_MAX_NEWLINES = _env_int("CASE1_REMARK_MAX_NEWLINES", 3)

# 模板选项或指标解释里内嵌的豁免条款
# 默认词表取自单份实测样本及其近义写法，不是通用真理；换模板可用环境变量覆盖
EXEMPTION_MARKERS = _env_list(
    "CASE1_EXEMPTION_MARKERS",
    ("不适用", "按满分", "视同满分", "不计分"),
)
_EXEMPTION_RE = re.compile(
    r"[（(][^（）()]*(?:"
    + "|".join(re.escape(marker) for marker in EXEMPTION_MARKERS)
    + r")[^（）()]*[）)]"
)


def exemption_clause(*texts: str) -> str:
    """返回文本中的豁免条款原文，没有则空串"""
    clauses = exemption_clauses(*texts)
    if clauses:
        return clauses[0]
    return ""


def exemption_clauses(*texts: str) -> list[str]:
    """提取文本中的全部模板内嵌豁免条款，按首次出现顺序去重"""
    clauses: list[str] = []
    for text in texts:
        for match in _EXEMPTION_RE.finditer(text or ""):
            clause = match.group(0)
            if clause not in clauses:
                clauses.append(clause)
    return clauses


def remark_self_negates(remark: str) -> str:
    """备注是否自称「不选此项」，返回命中的说法"""
    e = remark or ""
    for p in SELF_NEGATION_MARKERS:
        if p in e:
            return p
    return ""


def remark_draft_reason(remark: str) -> str:
    """备注是否混入模型的推演过程，返回判据说明；正常备注返回空串"""
    e = remark or ""
    for m in DRAFT_MARKERS:
        if m in e:
            return f"含思考过程标记「{m}」"
    newlines = e.count("\n")
    if newlines >= REMARK_MAX_NEWLINES:
        return f"含 {newlines} 个换行，疑为分条罗列的推演过程"
    if len(e) > REMARK_MAX_LEN:
        return f"长度 {len(e)} 字符，超出上限 {REMARK_MAX_LEN}"
    return ""


def check_yes_no_row(
    row_n: int, ind: str, choice: str, remark: str, option_text: str, explanation: str
) -> tuple[list[str], list[str]]:
    """校验一个 yes_no 行的内容质量，返回 (errors, warnings)"""
    errors: list[str] = []
    warnings: list[str] = []
    # 留空要检出，否则模型会拿它当被打回后的逃逸路径
    if not choice:
        msg = f"行{row_n}「{ind}」未填指标选择，须填「是」或「否」"
        (errors if empty_choice_is_error() else warnings).append(msg)
    clause = exemption_clause(option_text, explanation)
    if clause and choice == "否":
        warnings.append(
            f"行{row_n}「{ind}」填「否」，但该条目带豁免条款{clause}"
            f"——请确认本项目是否属于该情形，属于则应按满分填「是」"
        )
    draft = remark_draft_reason(remark) if (choice and remark) else ""
    if draft:
        warnings.append(
            f"行{row_n}「{ind}」备注混入推演过程（{draft}），只应写最终判断要点与引用"
        )
    return errors, warnings


def check_exclusive_pick(
    row_n: int, ind: str, choice: str, remark: str, rows: list, explanation: str
) -> tuple[list[str], list[str]]:
    """校验互斥组选中行的内容质量，返回 (errors, warnings)"""
    warnings: list[str] = []
    clause = exemption_clause(explanation, *[r.get("option_text") or "" for r in rows])
    # 选中项的全文写在组首行 D 列，故按文本比对而非行号
    best = str((rows[0] or {}).get("option_text") or "").strip() if rows else ""
    if clause and best and choice and choice != best:
        warnings.append(
            f"行{row_n}「{ind}」未选最优项，但该组带豁免条款{clause}"
            f"——请确认本项目是否属于该情形，属于则应按满分口径选最优项"
        )
    if remark:
        negation = remark_self_negates(remark)
        if negation:
            warnings.append(
                f"行{row_n}「{ind}」备注称「{negation}」却填了该选项，结论与选择相反"
            )
        draft = remark_draft_reason(remark)
        if draft:
            warnings.append(
                f"行{row_n}「{ind}」备注混入推演过程（{draft}），只应写最终判断要点与引用"
            )
    return [], warnings


def empty_choice_is_error() -> bool:
    """留空默认只提示不判失败

    材料千差万别，某些材料下整行无从判断是可能的；而堵住「模型拿留空当逃逸路径」
    靠的是检出后触发重填，不靠让任务失败。需要严格模式时置 CASE1_EMPTY_CHOICE_LEVEL=error。
    """
    return (os.environ.get("CASE1_EMPTY_CHOICE_LEVEL") or "warning").strip().lower() == "error"

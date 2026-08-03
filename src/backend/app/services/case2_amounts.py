"""金额文本归一化：救回分隔符被 OCR 认错的数字。

扫描件里千分位逗号常被读成句点（`1.758,823.768.78`），按常规解析会直接失败，
事实被静默丢弃。数字序列本身是对的，靠「末组两位是小数、其余组必须三位」就能
唯一还原。只在常规解析失败时才启用，正常写法一律原样通过。
"""

from __future__ import annotations

import re

_SEP_RE = re.compile(r"[.,]")
_SEP_ONLY_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _clean(text: str) -> tuple[str, bool]:
    """去掉首尾空白、全角逗号与括号负号，返回 (纯数字串, 是否为负)。

    **内部空白一律不吃掉**：`3,700,000.00 1,234.00` 是两个数，抹掉空格再按千分位
    重组会拼出一个凭空的 3,700,000,001,234.00。留着空格，后面的解析自然会拒绝它。
    """
    body = str(text).strip().replace("，", ",")
    negative = False
    if body[:1] in ("-", "−", "—"):
        negative = True
        body = body[1:]
    elif body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1]
    return body, negative


def _regroup(body: str) -> float | None:
    """分隔符错乱时按千分位重组；任何一组不合规就放弃，不猜。"""
    if not _SEP_ONLY_RE.fullmatch(body):
        return None
    groups = _SEP_RE.split(body)
    if len(groups) < 2:
        return None
    if len(groups[-1]) != 2:
        return None
    if not 1 <= len(groups[0]) <= 3:
        return None
    if any(len(group) != 3 for group in groups[1:-1]):
        return None
    try:
        return float("".join(groups[:-1]) + "." + groups[-1])
    except ValueError:
        return None


def parse_amount(value: object) -> float | None:
    """把金额文本解析成数字；解析不了返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    body, negative = _clean(str(value or ""))
    if not body:
        return None
    try:
        number = float(body.replace(",", ""))
    except ValueError:
        number = _regroup(body)
        if number is None:
            return None
    return -number if negative else number


def is_repaired(value: object) -> bool:
    """该值是否只能靠重组分隔符才解析得出——用于提示人工复核。"""
    if not isinstance(value, str):
        return False
    body, _ = _clean(value)
    if not body:
        return False
    try:
        float(body.replace(",", ""))
    except ValueError:
        return _regroup(body) is not None
    return False

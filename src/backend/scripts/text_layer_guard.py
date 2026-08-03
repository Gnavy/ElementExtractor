"""判断 PDF 自带文本层是否可信，不可信时让 Docling 强制整页 OCR。

部分客户材料是「先被别的软件 OCR 过一遍」的可搜索 PDF。Docling 默认信任已有
文本层、不再自己识别，那一份烂文本就被原样送进模型。

判据只数「确凿损坏的金额」，不算规范率——比例判据对「什么算候选」极其敏感，
列表序号 `1.` `2.` 会被当成畸形金额，把完好的文本层判成不可信。误判方向是
最坏的：把准确的文本层扔掉换成 OCR 结果。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# OCR 把数字读坏时特有的杂字符；正常金额里绝不出现
_GARBAGE_CHARS = "、`^~仝()[]{}\\|XxIlOo“”'＇"
_DIGIT_RE = re.compile(r"\d")
_INNER_SPACE_RE = re.compile(r"\d[\s　 ]+\d")
# 千分位分组：首组 1-3 位，其余必须 3 位
_GROUPED_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN_RE = re.compile(r"^-?\d+(\.\d+)?$")
# 日期不是金额，避免 2023-05-01 / 2023.05.01 被当成分组异常
_DATE_LIKE_RE = re.compile(r"^(19|20)\d{2}[-/.年]\d{1,2}([-/.月]\d{1,2}日?)?$")
_NUMERIC_ONLY_RE = re.compile(r"^-?[\d,.]+$")

# 金额至少要有这么多位数字；低于此数的（序号、页码、条目数）一律不看
_MIN_DIGITS = 5
# 一页出现这么多个确凿损坏的金额，才判该页文本层不可信
_MIN_BROKEN_PER_PAGE = 5


def _strip_blank(text: str) -> str:
    return re.sub(r"[\s　 ]", "", text)


def _is_wellformed(text: str) -> bool:
    """规范写法的数字（供测试与调试）"""
    body = _strip_blank(text)
    return bool(_GROUPED_RE.fullmatch(body) or _PLAIN_RE.fullmatch(body))


def _is_broken_amount(text: str) -> bool:
    """这个 token 是不是「本该是金额、但已被读坏」的数字。

    三条证据任一成立即判损坏；都不成立就当它正常，宁可漏判不可误判——
    误判会把好的文本层换成 OCR，代价比漏判大得多。
    """
    body = text.strip()
    if len(_DIGIT_RE.findall(body)) < _MIN_DIGITS:
        return False
    if _DATE_LIKE_RE.fullmatch(body):
        return False
    if any(ch in _GARBAGE_CHARS for ch in body):
        return True
    if _INNER_SPACE_RE.search(body):
        return True
    if _NUMERIC_ONLY_RE.fullmatch(body):
        # 只有数字和 , . 时，分组必须合法；`457,265,85905` 末组 5 位即为损坏
        return not (_GROUPED_RE.fullmatch(body) or _PLAIN_RE.fullmatch(body))
    return False


def _page_texts(page: Any) -> list[str]:
    cells = getattr(page, "textline_cells", None)
    if cells is None:
        return []
    return [str(getattr(cell, "text", "") or "").strip() for cell in cells]


def inspect_text_layer(
    pdf_path: Path, *, stop_on_first_suspect: bool = True
) -> dict[str, Any]:
    """返回文本层体检结果；解析不了就返回 supported=False，调用方保持原行为。

    逐页解析约 0.25 秒，默认一命中就停——判定只需要一页，全量页码清单是调试用的。
    """
    result: dict[str, Any] = {
        "supported": False,
        "pages": 0,
        "scanned_pages": 0,
        "broken": 0,
        "suspect_pages": [],
        "untrustworthy": False,
    }
    try:
        from docling_parse.pdf_parser import DoclingPdfParser
    except ImportError:
        return result

    try:
        doc = DoclingPdfParser().load(path_or_stream=str(pdf_path))
        total_pages = int(doc.number_of_pages())
    except Exception:  # noqa: BLE001 — 体检失败不应连累正常 OCR
        return result

    result["supported"] = True
    result["pages"] = total_pages
    for page_no in range(1, total_pages + 1):
        result["scanned_pages"] = page_no
        try:
            texts = _page_texts(doc.get_page(page_no))
        except Exception:  # noqa: BLE001
            continue
        broken = [text for text in texts if _is_broken_amount(text)]
        result["broken"] += len(broken)
        if len(broken) >= _MIN_BROKEN_PER_PAGE:
            result["suspect_pages"].append(page_no)
            if stop_on_first_suspect:
                break

    result["untrustworthy"] = bool(result["suspect_pages"])
    return result


def describe(report: dict[str, Any]) -> str:
    if not report.get("supported"):
        return "文本层体检未执行（docling_parse 不可用或解析失败）"
    pages = report.get("suspect_pages") or []
    if not pages:
        return (
            f"文本层体检通过：{report['pages']} 页，"
            f"损坏金额 {report['broken']} 个（阈值 {_MIN_BROKEN_PER_PAGE}/页）"
        )
    preview = ", ".join(str(p) for p in pages[:10])
    suffix = " 等" if len(pages) > 10 else ""
    return (
        f"文本层不可信：第 {preview}{suffix} 页出现确凿损坏的金额"
        f"（已扫描 {report['scanned_pages']}/{report['pages']} 页，"
        f"累计 {report['broken']} 个），本文件改用强制整页 OCR"
    )

"""Case2 复核提示收集与渲染。

对应业务说明 5.2.3：扫描件、复杂表格容易造成识别风险，平台应在结果中提示
需要人工复核的内容。这里只负责收集和展示提示，不改变任务状态、不修改数据。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REVIEW_NOTES_FILE = "case2_review_notes.json"

# 提示类型 -> 展示用标题
_KIND_TITLES = {
    "period_unmapped": "报告期未映射成功",
    "entity_variants": "公司名称识别存在多个版本",
    "carryforward_mismatch": "期间存在歧义（年初数与上期期末数对不上）",
    "calc_incomplete_sources": "合计项缺少组成项目，未计算",
    "template_placeholder_cleared": "已清除未填单元格中的模板提示文字",
    "template_check_failed": "模板核查检验未通过",
    "template_check_unparsed": "部分模板公式未参与校验",
    "period_date_from_evidence_text": "报告期取自证据说明文本",
    "user_rules_truncated": "用户填表规则过长，尾部未进入模型提示",
    "fact_not_grounded": "事实在源文档中找不到同行依据，已排除",
}


def _notes_path(extract_root: Path) -> Path:
    return Path(extract_root) / "outputs" / REVIEW_NOTES_FILE


def load_review_flags(extract_root: Path) -> list[dict[str, Any]]:
    path = _notes_path(extract_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    flags = data.get("flags") if isinstance(data, dict) else data
    return [flag for flag in (flags or []) if isinstance(flag, dict)]


def add_review_flags(
    extract_root: Path,
    flags: list[dict[str, Any]],
    *,
    stage: str,
) -> list[dict[str, Any]]:
    """追加复核提示；同一 stage 重跑时覆盖该 stage 的旧提示。"""
    existing = [
        flag for flag in load_review_flags(extract_root) if flag.get("stage") != stage
    ]
    merged = existing + [{**flag, "stage": stage} for flag in flags]
    path = _notes_path(extract_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"flags": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged


def render_markdown(flags: list[dict[str, Any]]) -> str:
    if not flags:
        return "\n## 需人工复核\n\n本次填报未产生复核提示。\n"
    lines = ["", "## 需人工复核", ""]
    lines.append(f"共 {len(flags)} 项，下载 Excel 后请优先核对以下内容：")
    lines.append("")
    for index, flag in enumerate(flags, start=1):
        kind = str(flag.get("kind") or "")
        title = _KIND_TITLES.get(kind, kind or "复核提示")
        detail = str(flag.get("detail") or "").strip()
        scope = " ".join(
            str(flag.get(key))
            for key in ("sheet_name", "column_label", "statement", "target")
            if flag.get(key)
        )
        head = f"{index}. **{title}**"
        if scope:
            head += f"（{scope}）"
        lines.append(head)
        if detail:
            lines.append(f"   - {detail}")
    lines.append("")
    return "\n".join(lines)


def append_review_section(extract_root: Path) -> int:
    """把复核提示追加到 collection_fill_notes.md 末尾，返回提示条数。"""
    flags = load_review_flags(extract_root)
    notes = Path(extract_root) / "outputs" / "collection_fill_notes.md"
    if not notes.is_file():
        return len(flags)
    text = notes.read_text(encoding="utf-8")
    marker = "## 需人工复核"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    notes.write_text(text.rstrip() + "\n" + render_markdown(flags), encoding="utf-8")
    return len(flags)

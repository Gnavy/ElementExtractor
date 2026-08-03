"""把上一轮的校验结果回传给重填的指标组。

修复轮原本只传组名，重填时模型拿到的输入与上一轮完全相同，等于重掷骰子——
实测行15 连续两轮整组留空、行31 五轮都留草稿备注，都是这么来的。

这里只做一件事：把系统自己已经查出来的问题告诉模型，让它知道上次错在哪。
不新增判断规则，不提供答案，不改写填报值。
"""

from __future__ import annotations

import json
from pathlib import Path

# 只回传「模型自己能改」的结构与格式类问题。
# 豁免提示（「请确认本项目是否属于该情形」）刻意排除：属不属于豁免是业务判断，
# 模型判断不了，硬塞给它只会诱导它往宽里填。
_ACTIONABLE_MARKERS = (
    "未填指标选择",
    "结论与选择相反",
    "备注混入推演过程",
    "缺少源文件名与原文引用",
    "指标选择须为是/否",
    "未选择任何选项",
    "有多行填了指标选择",
    "备注为空",
)


def previous_issues_for_group(extract_root: Path | str, indicator_name: str) -> str:
    """返回本组上一轮的待修正问题；首轮、无报告或无问题时返回空串"""
    name = (indicator_name or "").strip()
    if not name:
        return ""
    report_path = Path(extract_root) / "outputs" / "validation_report.json"
    if not report_path.is_file():
        return ""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    issues: list[str] = []
    for msg in (report.get("errors") or []) + (report.get("warnings") or []):
        text = str(msg)
        if name not in text:
            continue
        if not any(m in text for m in _ACTIONABLE_MARKERS):
            continue
        if text not in issues:
            issues.append(text)
    if not issues:
        return ""

    listed = "\n".join(f"- {x}" for x in issues)
    return (
        "【上一轮本组的校验问题】\n"
        f"{listed}\n"
        "请在本次填报中逐条修正。仍以材料为准：不要为了消除上述提示而编造内容，"
        "材料确无依据时照常填「否」或选兜底项，并在备注写明未检索到的内容。"
    )

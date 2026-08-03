from __future__ import annotations

import json
from pathlib import Path

from app.services.case1_retry_hints import previous_issues_for_group


def _write_report(tmp_path: Path, errors: list[str], warnings: list[str]) -> Path:
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "validation_report.json").write_text(
        json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


def test_no_report_returns_empty(tmp_path):
    """首轮没有校验报告，必须静默返回空，不能影响首次填报"""
    assert previous_issues_for_group(tmp_path, "任意指标") == ""


def test_returns_only_issues_of_this_group(tmp_path):
    root = _write_report(
        tmp_path,
        errors=["互斥组「原债权人对项目的投后监管力度」未选择任何选项（应恰选 1 项）"],
        warnings=["行31「板块内同类型用地土拍情况」备注混入推演过程（含思考过程标记「重新计算」）"],
    )

    hint = previous_issues_for_group(root, "原债权人对项目的投后监管力度")
    assert "未选择任何选项" in hint
    # 别组的问题不得混进来
    assert "板块内同类型用地土拍情况" not in hint
    # 防止模型为了消警报而编造
    assert "不要为了消除上述提示而编造内容" in hint


def test_exemption_hint_is_not_fed_back(tmp_path):
    """豁免提示刻意排除——属不属于豁免是业务判断，塞给模型只会诱导它往宽里填"""
    root = _write_report(
        tmp_path,
        errors=[],
        warnings=[
            "行13「现金流入流出的确定性约定」填「否」，但该条目带豁免条款"
            "（如果为介入前尚未开始预售的项目，该条目不适用按满分处理）——请确认本项目是否属于该情形"
        ],
    )

    assert previous_issues_for_group(root, "现金流入流出的确定性约定") == ""


def test_group_without_issues_returns_empty(tmp_path):
    root = _write_report(
        tmp_path,
        errors=[],
        warnings=["行31「板块内同类型用地土拍情况」备注混入推演过程（含 21 个换行）"],
    )

    assert previous_issues_for_group(root, "增信措施约定") == ""


def test_broken_report_does_not_crash(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "validation_report.json").write_text("{不是合法 JSON", encoding="utf-8")

    assert previous_issues_for_group(tmp_path, "增信措施约定") == ""


def test_prompt_placeholder_is_wired(tmp_path):
    """prompts 新增占位符后，所有调用点都必须传值，否则 format 会 KeyError"""
    from app.agents.prompts import case1 as prompts

    filled = prompts.FILL_GROUP_USER.format(
        task_id="t",
        region="成都市",
        user_rules="（无）",
        indicator_name="增信措施约定",
        indicator_explanation="",
        choice_mode="yes_no",
        allowed_choices="[]",
        data_source_priority="尽调报告",
        requires_tavily=False,
        tavily_hint="",
        rows_json="[]",
        retry_hints="",
        tavily_md="（无）",
        context="（无）",
    )
    assert "增信措施约定" in filled

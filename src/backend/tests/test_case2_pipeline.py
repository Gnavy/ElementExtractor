from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError

from app.agents import llm as llm_module
from app.agents.llm import structured_llm
from app.agents.nodes.case2.evidence import (
    _carryforward_review_flags,
    _entity_match_kind,
    _missing_ocr_sources,
    _route_evidence_chunks,
    _validate_sheet_identity,
    build_case2_ocr_chunks,
    facts_for_fill,
    facts_for_item_ids,
)
from app.agents.nodes.case2.fill_items import (
    _annotate_unmapped_columns,
    _normalize_value,
)
from app.agents.schemas.case2_item import (
    Case2BatchFill,
    Case2ChunkEvidence,
    Case2ItemFill,
    Case2PeriodMap,
)
from app.services.case2_schema_pipeline import (
    backfill_case2_schema,
    validate_case2_backfill,
)


def test_case2_ocr_chunks_cover_entire_markdown(tmp_path: Path):
    ocr_dir = tmp_path / "ocr_text"
    ocr_dir.mkdir()
    markers = [f"MARKER_{index:02d}" for index in range(12)]
    text = "\n".join(f"{marker} " + ("内容" * 45) for marker in markers)
    (ocr_dir / "report.md").write_text(text, encoding="utf-8")

    chunks = build_case2_ocr_chunks(tmp_path, max_chars=260, overlap=40)

    assert len(chunks) > 1
    combined = "\n".join(chunk["text"] for chunk in chunks)
    assert all(marker in combined for marker in markers)
    assert {chunk["source_ref"] for chunk in chunks} == {"ocr_text/report.md"}


def test_structured_llm_honors_explicit_method_for_openai(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.calls = []

        def with_structured_output(self, schema, *, method):
            self.calls.append((schema, method))
            return "bound"

    model = FakeModel()
    monkeypatch.setattr(llm_module, "_is_bailian_family", lambda: False)

    result = structured_llm(dict, model=model, method="json_mode")

    assert result == "bound"
    assert model.calls == [(dict, "json_mode")]


def test_case2_ocr_chunks_fall_back_to_sidecar(tmp_path: Path):
    ocr_dir = tmp_path / "ocr_text"
    ocr_dir.mkdir()
    (ocr_dir / "scan.pdf.md").write_text("<!-- image -->", encoding="utf-8")
    (ocr_dir / "scan.pdf.ocr_cells.json").write_text(
        json.dumps(
            {
                "cells": [
                    {"page": 1, "text": "营业收入 100"},
                    {"page": 2, "text": "净利润 20"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    chunks = build_case2_ocr_chunks(tmp_path, max_chars=260, overlap=40)

    assert len(chunks) == 1
    assert "营业收入 100" in chunks[0]["text"]
    assert "净利润 20" in chunks[0]["text"]


def test_case2_ocr_chunks_preserve_scanned_page_markers(tmp_path: Path):
    ocr_dir = tmp_path / "ocr_text"
    ocr_dir.mkdir()
    (ocr_dir / "scan.md").write_text(
        "<!-- image -->\n第一页 " + ("甲" * 100)
        + "\n<!-- image -->\n第二页 "
        + ("乙" * 100),
        encoding="utf-8",
    )

    chunks = build_case2_ocr_chunks(tmp_path, max_chars=260, overlap=40)

    assert [chunk["page"] for chunk in chunks] == [1, 2]
    assert "第一页" in chunks[0]["text"]
    assert "第二页" in chunks[1]["text"]


def test_case2_ocr_chunks_restore_missing_page_header_from_sidecar(
    tmp_path: Path,
):
    ocr_dir = tmp_path / "ocr_text"
    ocr_dir.mkdir()
    (ocr_dir / "scan.pdf.md").write_text(
        "<!-- image -->\n第一页正文 "
        + ("甲" * 100)
        + "\n<!-- image -->\n| 营业收入 | 100 |",
        encoding="utf-8",
    )
    (ocr_dir / "scan.pdf.ocr_cells.json").write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "page": 2,
                        "text": "利润表",
                        "bbox": [0.4, 0.05, 0.6, 0.1],
                    },
                    {
                        "page": 2,
                        "text": "2022年12期",
                        "bbox": [0.4, 0.1, 0.6, 0.15],
                    },
                    {
                        "page": 2,
                        "text": "营业收入 100",
                        "bbox": [0.1, 0.5, 0.9, 0.55],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    chunks = build_case2_ocr_chunks(tmp_path, max_chars=500, overlap=40)

    assert chunks[1]["page"] == 2
    assert "OCR 页眉补充" in chunks[1]["text"]
    assert "利润表" in chunks[1]["text"]
    assert "2022年12期" in chunks[1]["text"]
    assert "营业收入 100" not in chunks[1]["text"]


def test_case2_fact_filter_and_value_normalization():
    catalog = {
        "facts": [
            {"item_id": "利润表:r5", "value": 10},
            {"item_id": "利润表:r6", "value": 20},
        ]
    }
    assert facts_for_item_ids(catalog, {"利润表:r6"}) == [
        {"item_id": "利润表:r6", "value": 20}
    ]
    assert _normalize_value("1,234.50", "number") == 1234.5
    assert _normalize_value("(12.5)", "number") == -12.5
    assert _normalize_value("null", "number") is None


def test_case2_schema_rejects_corrupted_structured_output():
    with pytest.raises(ValidationError):
        Case2ItemFill(
            item_id="利润表:r5",
            fields={"C": {"value": 1}},
            confidence="reason_one_line",
        )


def test_case2_item_unwraps_json_mode_field_values():
    item = Case2ItemFill.model_validate(
        {
            "item_id": "利润表:r6",
            "fields": {
                "C": {
                    "value": 100,
                    "evidence": "营业收入 100",
                }
            },
        }
    )

    assert item.fields == {"C": 100}


def test_case2_schema_wraps_single_objects_for_array_fields():
    evidence = Case2ChunkEvidence.model_validate(
        {
            "period_hints": {
                "statement_name": "利润表",
                "source_period": "本期金额",
                "evidence_text": "本期金额",
            },
            "facts": {
                "item_id": "利润表:r6",
                "subject_name": "营业收入",
                "source_period": "本期金额",
                "value": 100,
                "evidence_text": "营业收入 100",
            },
        }
    )
    batch = Case2BatchFill.model_validate(
        {"items": {"item_id": "利润表:r6", "fields": {"C": 100}}}
    )
    period_map = Case2PeriodMap.model_validate(
        {
            "columns": {
                "sheet_name": "利润表",
                "field_key": "C",
                "column_label": "最近一期",
            }
        }
    )

    assert len(evidence.period_hints) == 1
    assert len(evidence.facts) == 1
    assert evidence.facts[0].subject_name == "营业收入"
    assert len(batch.items) == 1
    assert len(period_map.columns) == 1


def test_case2_period_map_accepts_json_mode_aliases():
    period_map = Case2PeriodMap.model_validate(
        {
            "columns": {
                "template_column": "C",
                "report_date": "2023-03-31",
                "evidence": "最近一期报告",
            }
        }
    )

    assert period_map.columns[0].field_key == "C"
    assert period_map.columns[0].evidence_text == "最近一期报告"


def test_case2_schema_parses_labeled_period_hints():
    evidence = Case2ChunkEvidence.model_validate(
        {
            "period_hints": [
                "企业主体: 示例公司",
                "报告日期: 2023年12月31日",
            ],
            "facts": [],
        }
    )

    assert len(evidence.period_hints) == 1
    assert evidence.period_hints[0].entity_name == "示例公司"
    assert evidence.period_hints[0].report_date == "2023年12月31日"


def test_case2_fact_ignores_redundant_unknown_fields():
    evidence = Case2ChunkEvidence.model_validate(
        {
            "period_hints": [],
            "facts": {
                "item_id": "利润表:r6",
                "source_period": "本期金额",
                "value": 100,
                "evidence_text": "营业收入 100",
                "period_hints": ["报告日期: 2023年12月31日"],
            },
        }
    )

    assert evidence.facts[0].model_dump().get("period_hints") is None


def test_case2_period_hint_without_evidence_is_not_kept(monkeypatch):
    from app.agents.nodes.case2 import evidence as evidence_module

    class FakeRunnable:
        def invoke(self, _messages, **_kwargs):
            return Case2ChunkEvidence.model_validate(
                {
                    "period_hints": {
                        "statement_name": "利润表",
                        "source_period": "本期金额",
                    },
                    "facts": [],
                }
            )

    monkeypatch.setattr(
        evidence_module,
        "structured_llm",
        lambda *_args, **_kwargs: FakeRunnable(),
    )

    result = evidence_module.extract_evidence_chunk_node(
        {
            "task_id": "task",
            "material_chunk": {
                "source_ref": "ocr_text/report.md",
                "page": 1,
                "text": "利润表",
                "statement_hints": ["利润表"],
            },
            "evidence_targets": [],
            "chunk_index": 0,
            "total_chunks": 1,
        }
    )

    assert result["chunk_evidence"][0]["period_hints"] == []


def test_case2_null_fact_is_not_kept(monkeypatch):
    from app.agents.nodes.case2 import evidence as evidence_module

    class FakeRunnable:
        def invoke(self, _messages, **_kwargs):
            return Case2ChunkEvidence.model_validate(
                {
                    "period_hints": [],
                    "facts": {
                        "item_id": "利润表:r4",
                        "subject_name": "报告期",
                        "source_period": "本期金额",
                        "value": None,
                        "evidence_text": "2023年12期",
                    },
                }
            )

    monkeypatch.setattr(
        evidence_module,
        "structured_llm",
        lambda *_args, **_kwargs: FakeRunnable(),
    )

    result = evidence_module.extract_evidence_chunk_node(
        {
            "task_id": "task",
            "material_chunk": {
                "source_ref": "ocr_text/report.md",
                "page": 1,
                "text": "利润表",
            },
            "evidence_targets": [{"item_id": "利润表:r4"}],
            "chunk_index": 0,
            "total_chunks": 1,
        }
    )

    assert result["chunk_evidence"][0]["facts"] == []


def test_case2_routes_all_sources_but_only_financial_candidates():
    chunks = [
        {
            "source_ref": "ocr_text/audit.pdf.md",
            "source_name": "audit.pdf",
            "text": "合并资产负债表 货币资金 100",
        },
        {
            "source_ref": "ocr_text/audit.pdf.md",
            "source_name": "audit.pdf",
            "text": "审计意见和会计政策说明",
        },
        {
            "source_ref": "ocr_text/report.docx.md",
            "source_name": "report.docx",
            "text": "利润表分析 营业收入 200",
        },
    ]
    targets = [
        {
            "item_id": "资产负债表:r6",
            "sheet_name": "资产负债表",
            "label": "货币资金",
        },
        {
            "item_id": "利润表:r6",
            "sheet_name": "利润表",
            "label": "营业收入",
        },
    ]

    routed, inventory = _route_evidence_chunks(chunks, targets)

    assert len(routed) == 2
    assert {chunk["source_ref"] for chunk in routed} == {
        "ocr_text/audit.pdf.md",
        "ocr_text/report.docx.md",
    }
    assert sum(item["total_chunks"] for item in inventory) == 3
    assert sum(item["candidate_chunks"] for item in inventory) == 2


def test_case2_detects_source_without_ocr_text(tmp_path: Path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"pdf")
    (source_dir / "b.docx").write_bytes(b"docx")

    missing = _missing_ocr_sources(
        tmp_path,
        [{"source_name": "a.pdf"}],
    )

    assert missing == ["b.docx"]


def _template_check_book(tmp_path: Path, formulas: dict[str, str], values: dict):
    """造一张带核查公式的小模板，行为与客户模板同构。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "资产负债表"
    for coord, value in values.items():
        ws[coord] = value
    for coord, formula in formulas.items():
        ws[coord] = formula
    path = tmp_path / "filled.xlsx"
    wb.save(path)
    return path


def test_template_checks_report_delta_and_locate_suspect_cell(tmp_path: Path):
    from app.services.case2_template_checks import (
        evaluate_checks,
        read_template_checks,
        summarize,
    )

    # 归母 + 少数股东权益 = 所有者权益合计，此处归母被漏填成 0
    path = _template_check_book(
        tmp_path,
        {
            "C50": '=IF(ABS(SUM(C10:C11)-C12)<1,"无误","所有者权益合计有误")',
            "C51": '=IF(ABS(SUM(C10:C11)-C12)<1,"无误","另一条")',
        },
        {"C10": 0, "C11": 46_418_122.14, "C12": 106_959_211.58},
    )
    outcomes = evaluate_checks(path, read_template_checks(path))
    assert summarize(outcomes)["failed"] == 2
    failed = outcomes[0]
    assert failed.check.message == "所有者权益合计有误"
    assert abs(failed.delta + 60_541_089.44) < 0.01


def test_template_checks_flag_cell_equal_to_delta(tmp_path: Path):
    """差额恰好等于某个被引用格的值时，要把那一格点出来。"""
    from app.services.case2_template_checks import evaluate_checks, read_template_checks

    # C11 被重复计入，差额正好等于 C11
    path = _template_check_book(
        tmp_path,
        {"C50": '=IF(ABS(SUM(C10:C11)-C12)<1,"无误","合计有误")'},
        {"C10": 100.0, "C11": 25.0, "C12": 100.0},
    )
    outcome = evaluate_checks(path, read_template_checks(path))[0]
    assert outcome.ok is False
    assert outcome.delta_matches == ["C11"]


def test_template_checks_solve_single_empty_cell(tmp_path: Path):
    from app.services.case2_template_checks import evaluate_checks, read_template_checks

    path = _template_check_book(
        tmp_path,
        {"C50": '=IF(ABS(SUM(C10:C11)-C12)<1,"无误","合计有误")'},
        {"C11": 46_418_122.14, "C12": 106_959_211.58},  # C10 真空着
    )
    outcome = evaluate_checks(path, read_template_checks(path))[0]
    assert outcome.empty_refs == ["C10"]
    assert outcome.suggestion is not None
    coord, value = outcome.suggestion
    assert coord == "C10"
    assert abs(value - 60_541_089.44) < 0.01


def test_template_checks_mark_unsupported_formula_as_unchecked(tmp_path: Path):
    """认不出的公式必须标「未校验」，绝不能当成通过。"""
    from app.services.case2_template_checks import (
        check_review_flags,
        evaluate_checks,
        read_template_checks,
        summarize,
    )

    path = _template_check_book(
        tmp_path,
        {
            "C50": '=IF(VLOOKUP(C10,A1:B9,2,FALSE)>0,"无误","不支持的写法")',
            "C51": "=C4",
        },
        {"C10": 1.0},
    )
    outcomes = evaluate_checks(path, read_template_checks(path))
    stats = summarize(outcomes)
    assert stats["passed"] == 0
    assert stats["unchecked"] == 1
    assert stats["mirror_cells"] == 1  # =C4 是镜像取值，不计入未校验
    assert any(f["kind"] == "template_check_unparsed" for f in check_review_flags(outcomes))


def test_case2_period_map_accepts_unmappable_column_with_blank_fields():
    """材料缺某一期时模型会把该列各字段留空，不能让整份映射解析失败。"""
    period_map = Case2PeriodMap.model_validate(
        {
            "columns": [
                {
                    "sheet_name": "利润表",
                    "field_key": "C",
                    "statement_scope": "合并",
                    "report_date": "2023-12-31",
                },
                {
                    "sheet_name": "利润表",
                    "field_key": "F",
                    "statement_scope": "",
                    "report_date": "",
                    "entity_name": "",
                    "source_ref": "",
                    "confidence": "low",
                    "evidence_text": "材料中无 2020 年完整年报，无法映射",
                },
            ]
        }
    )

    unmapped = period_map.columns[1]
    assert unmapped.statement_scope == "未知"
    assert unmapped.report_date is None
    assert unmapped.entity_name is None


def test_upload_zip_md5_stable_for_same_sources(tmp_path: Path):
    """相同源文件须打出相同 MD5，历史任务的 OCR 结果才能被复用。"""
    import hashlib

    from app.services.upload_zip_builder import build_zip_from_pairs

    pairs = [("b.pdf", b"world" * 100), ("a.pdf", b"hello" * 100)]

    def md5_of(name: str, extras) -> str:
        dest = tmp_path / name
        build_zip_from_pairs(dest, extras=extras, extras_prefix="sources")
        return hashlib.md5(dest.read_bytes()).hexdigest()

    first = md5_of("one.zip", pairs)
    assert first == md5_of("two.zip", pairs)
    assert first == md5_of("three.zip", list(reversed(pairs)))
    assert first != md5_of(
        "four.zip", [("b.pdf", b"world" * 100), ("a.pdf", b"HELLO" * 100)]
    )


def _calc_module():
    import sys
    from pathlib import Path as _P

    scripts = str(_P(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import apply_case2_calc_rules

    return apply_case2_calc_rules


def test_calc_sum_overwrites_model_value_and_flags_it():
    """sum/diff 以规则为准，覆盖已有值并留痕。"""
    calc = _calc_module()
    data = {"sheets": [{"sheet": "资产负债表", "items": [
        {"item_id": "r9", "label": "应收票据及应收账款",
         "fields": {"D": {"cell": "D9", "value": 465147735.17}}},
        {"item_id": "r10", "label": "其中:应收票据",
         "fields": {"D": {"cell": "D10", "value": 110516.93}}},
        {"item_id": "r11", "label": "应收账款",
         "fields": {"D": {"cell": "D11", "value": 354537218.24}}},
    ]}]}
    report = calc.apply_calc_rules(data, [{
        "op": "sum", "sheet": "资产负债表",
        "target_label": "应收票据及应收账款",
        "source_labels": ["其中应收票据", "应收账款"],
    }])

    assert data["sheets"][0]["items"][0]["fields"]["D"]["value"] == 354647735.17
    assert report["applied"][0]["overwrote"] == 465147735.17
    assert any(f["kind"] == "calc_overwrote_model_value" for f in report["review_flags"])


def test_calc_sum_partial_sources_fill_empty_but_never_overwrite():
    """来源缺值时部分和只能补空格，不得覆盖模型已填的完整值。"""
    calc = _calc_module()
    data = {"sheets": [{"sheet": "资产负债表", "items": [
        {"item_id": "r64", "label": "应付票据及应付账款",
         "fields": {"D": {"cell": "D64", "value": 425997938.46},
                    "C": {"cell": "C64", "value": None}}},
        {"item_id": "r65", "label": "其中:应付票据",
         "fields": {"D": {"cell": "D65", "value": None},
                    "C": {"cell": "C65", "value": None}}},
        {"item_id": "r66", "label": "应付账款",
         "fields": {"D": {"cell": "D66", "value": 325897828.35},
                    "C": {"cell": "C66", "value": 342192538.05}}},
    ]}]}
    report = calc.apply_calc_rules(data, [{
        "op": "sum", "sheet": "资产负债表",
        "target_label": "应付票据及应付账款",
        "source_labels": ["其中应付票据", "应付账款"],
    }])

    fields = data["sheets"][0]["items"][0]["fields"]
    # D 已有值且来源不全：保留模型值
    assert fields["D"]["value"] == 425997938.46
    assert any("incomplete sources" in str(s.get("reason")) for s in report["skipped"])
    # C 为空：部分和可以补
    assert fields["C"]["value"] == 342192538.05


def test_calc_diff_subtracts_and_requires_all_sources():
    calc = _calc_module()
    data = {"sheets": [{"sheet": "资产负债表", "items": [
        {"item_id": "r119", "label": "归属于母公司所有者权益合计",
         "fields": {"F": {"cell": "F119", "value": None}, "E": {"cell": "E119", "value": None}}},
        {"item_id": "r120", "label": "少数股东权益",
         "fields": {"F": {"cell": "F120", "value": 46418122.14}, "E": {"cell": "E120", "value": None}}},
        {"item_id": "r121", "label": "所有者权益合计",
         "fields": {"F": {"cell": "F121", "value": 106959211.58}, "E": {"cell": "E121", "value": 601800680.28}}},
    ]}]}
    report = calc.apply_calc_rules(data, [{
        "op": "diff", "sheet": "资产负债表",
        "target_label": "归属于母公司所有者权益合计",
        "source_labels": ["所有者权益合计", "少数股东权益"],
    }])

    fields = data["sheets"][0]["items"][0]["fields"]
    assert fields["F"]["value"] == 60541089.44
    # E 列少数股东权益缺值：差额缺任一来源都不算，不出半截差额
    assert fields["E"]["value"] is None
    assert any("missing source value" in str(s.get("reason")) for s in report["skipped"])


def test_llm_guard_aborts_whitespace_degeneration_in_streaming():
    """量化模型在 JSON 冒号后无限吐空格时，必须在流式过程中被中止。

    这里走真实的 langchain 流式管道，因为 handler 抛的异常默认会被
    handle_event 吞掉，只有 raise_error=True 才会向上传播。
    """
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from app.agents.llm import LLMDegenerationError, guard_config

    degenerate = '{"confidence":' + " " * 3000 + "1}"
    model = GenericFakeChatModel(messages=iter([AIMessage(content=degenerate)]))
    with pytest.raises(LLMDegenerationError):
        for _ in model.stream("hi", config=guard_config()):
            pass


def test_llm_guard_does_not_trip_on_normal_indented_json():
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from app.agents.llm import guard_config

    pretty = json.dumps(
        {"facts": [{"item_id": f"r{i}", "value": i} for i in range(40)]},
        ensure_ascii=False,
        indent=4,
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content=pretty)]))
    chunks = list(model.stream("hi", config=guard_config()))
    assert chunks


def test_llm_guard_uses_fresh_handler_per_call():
    """证据抽取是 8 路并发，共用 handler 会把各路的空白游程算到一起。"""
    from app.agents.llm import guard_config

    first = guard_config()["callbacks"][0]
    second = guard_config()["callbacks"][0]
    assert first is not second


def test_llm_fallback_cap_only_when_streaming_off(monkeypatch):
    """非流式时探测器拿不到 token 回调，必须退回硬上限，不能毫无保护。"""
    from app.agents import llm as llm_module

    monkeypatch.setattr(llm_module.settings, "llm_streaming", True, raising=False)
    assert llm_module.fallback_max_tokens(16384) == {}

    monkeypatch.setattr(llm_module.settings, "llm_streaming", False, raising=False)
    assert llm_module.fallback_max_tokens(16384) == {"max_tokens": 16384}


def test_case2_entity_ocr_typo_is_same_subject_but_group_suffix_is_not():
    """扫描件公司名错一个字要当同一家；「集团」这种成分差异不能当同一家。"""
    assert _entity_match_kind("东厦建设开发集团有限公司", "东度建设开发集团有限公司") == "fuzzy"
    assert (
        _entity_match_kind("东厦建设开发集团有限公司", "东厦建设开发团有限公司（并）")
        == "fuzzy"
    )
    assert _entity_match_kind("东厦建设开发集团有限公司", "东厦建设开发有限公司") == "none"
    assert _entity_match_kind("山东尊创置业有限公司", "山东新鸿置业有限公司") == "none"
    # 短名字差一个字不能当同一家
    assert _entity_match_kind("甲公司", "乙公司") == "none"


def test_case2_facts_survive_entity_name_ocr_typo():
    """同一份材料里公司名被 OCR 认错，不能因此丢掉整页证据。"""
    catalog = {
        "source_inventory": [{"source_ref": "ocr_text/a.pdf.md"}],
        "facts": [
            {
                "item_id": "资产负债表:r6",
                "entity_name": "东度建设开发集团有限公司",
                "statement_scope": "合并",
                "statement_name": "资产负债表",
                "report_date": "2022-12-31",
                "value": 248573298.6,
                "source_ref": "ocr_text/a.pdf.md",
            }
        ],
    }
    period_mapping = {
        "columns": [
            {
                "sheet_name": "资产负债表",
                "field_key": "D",
                "entity_name": "东厦建设开发集团有限公司",
                "statement_scope": "合并",
                "report_date": "2022-12-31",
            }
        ]
    }

    facts = facts_for_fill(
        catalog,
        {"资产负债表:r6"},
        sheet_name="资产负债表",
        period_mapping=period_mapping,
    )

    assert [fact["value"] for fact in facts] == [248573298.6]


def test_case2_carryforward_mismatch_is_flagged_without_changing_data():
    """本期年初数与上期期末数对不上时只报复核提示。"""
    def fact(report_date: str, period: str, subject: str, value: float) -> dict:
        return {
            "statement_name": "资产负债表",
            "report_date": report_date,
            "source_period": period,
            "subject_name": subject,
            "value": value,
        }

    subjects = ("货币资金", "应收账款", "资产总计", "流动资产合计")
    catalog = {
        "facts": [
            # 2020 年末
            *(fact("2020-12-31", "期末数", name, 100.0) for name in subjects),
            # 2021 页的「年初数」应等于上面这组，但这里整体对不上
            *(fact("2021-12-31", "年初数", name, 900.0) for name in subjects),
            # 2022 页的年初数与 2021 期末数一致，不应报
            *(fact("2021-12-31", "期末数", name, 500.0) for name in subjects),
            *(fact("2022-12-31", "年初数", name, 500.0) for name in subjects),
        ]
    }

    flags = _carryforward_review_flags(catalog)

    assert [flag["report_date"] for flag in flags] == ["2021-12-31"]
    assert flags[0]["kind"] == "carryforward_mismatch"
    # 只提示，不改动任何事实
    assert catalog["facts"][4]["value"] == 900.0


def test_case2_unmapped_column_reason_is_not_reported_as_missing_source():
    schema = {
        "sheets": [
            {
                "sheet": "资产负债表",
                "items": [
                    {
                        "item_id": "资产负债表:r6",
                        "fields": {
                            "C": {"cell": "C6", "value": None},
                            "E": {"cell": "E6", "value": None},
                        },
                        "reason_one_line": "文件中未发现相关信息",
                    },
                    {
                        "item_id": "资产负债表:r9",
                        "fields": {"E": {"cell": "E9", "value": 1.0}},
                        "reason_one_line": "文件中未发现相关信息",
                    },
                ],
            }
        ]
    }
    period_mapping = {
        "columns": [
            {
                "sheet_name": "资产负债表",
                "field_key": "C",
                "column_label": "最近一期报告",
                "report_date": None,
            },
            {
                "sheet_name": "资产负债表",
                "field_key": "E",
                "column_label": "上期(年报)",
                "report_date": "2021-12-31",
            },
        ]
    }

    _annotate_unmapped_columns(schema, period_mapping)
    items = schema["sheets"][0]["items"]

    assert "未映射成功" in items[0]["reason_one_line"]
    assert "非源文件缺失" in items[0]["reason_one_line"]
    # 有值的行不加注
    assert items[1]["reason_one_line"] == "文件中未发现相关信息"

    # 重复执行不叠加
    _annotate_unmapped_columns(schema, period_mapping)
    assert items[0]["reason_one_line"].count("未映射成功") == 1


def test_case2_facts_do_not_mix_entities_or_statement_scopes():
    catalog = {
        "facts": [
            {
                "item_id": "利润表:r6",
                "entity_name": "甲公司",
                "statement_scope": "合并",
                "statement_name": "利润表",
                "report_date": "2023-12-31",
                "value": 100,
                "source_ref": "ocr_text/a.pdf.md",
            },
            {
                "item_id": "利润表:r6",
                "entity_name": "乙公司",
                "statement_scope": "合并",
                "statement_name": "利润表",
                "report_date": "2023-12-31",
                "value": 200,
                "source_ref": "ocr_text/b.pdf.md",
            },
            {
                "item_id": "利润表:r6",
                "entity_name": "甲公司",
                "statement_scope": "母公司",
                "statement_name": "利润表",
                "report_date": "2023-12-31",
                "value": 300,
                "source_ref": "ocr_text/c.pdf.md",
            },
        ]
    }
    period_mapping = {
        "columns": [
            {
                "sheet_name": "利润表",
                "field_key": "C",
                "entity_name": "甲公司",
                "statement_scope": "合并",
                "report_date": "2023-12-31",
                "source_ref": "ocr_text/a.pdf.md",
            }
        ]
    }

    facts = facts_for_fill(
        catalog,
        {"利润表:r6"},
        sheet_name="利润表",
        period_mapping=period_mapping,
    )

    assert [fact["value"] for fact in facts] == [100]


def test_case2_facts_match_entity_alias_and_date_format():
    catalog = {
        "facts": [
            {
                "item_id": "利润表:r6",
                "entity_name": "东厦",
                "statement_scope": "合并",
                "statement_name": "利润表",
                "report_date": "2022年12月31日",
                "value": 100,
                "source_ref": "ocr_text/a.pdf.md",
            }
        ]
    }
    period_mapping = {
        "columns": [
            {
                "sheet_name": "利润表",
                "field_key": "D",
                "entity_name": "东厦建设开发集团有限公司",
                "statement_scope": "合并",
                "report_date": "2022-12-31",
                "source_ref": "ocr_text/a.pdf.md",
            }
        ]
    }

    facts = facts_for_fill(
        catalog,
        {"利润表:r6"},
        sheet_name="利润表",
        period_mapping=period_mapping,
    )

    assert [fact["value"] for fact in facts] == [100]


def test_case2_period_mapping_rejects_mixed_entities():
    with pytest.raises(RuntimeError, match="多个企业主体"):
        _validate_sheet_identity(
            [
                {"sheet_name": "利润表", "entity_name": "甲公司"},
                {"sheet_name": "利润表", "entity_name": "乙公司"},
            ]
        )


def test_case2_period_mapping_unifies_entity_ocr_variants():
    """同一主体被 OCR 认成几个变体时不能判为「混入多个企业主体」而终止任务。"""
    columns = [
        {"sheet_name": "资产负债表", "field_key": "C", "entity_name": "东厦建设开发团有限公司（并）"},
        {"sheet_name": "资产负债表", "field_key": "D", "entity_name": "东度建设开发集团有限公司"},
        {"sheet_name": "资产负债表", "field_key": "E", "entity_name": "东厦建设开发集团有限公司"},
    ]

    _validate_sheet_identity(columns, preferred_entity="东厦建设开发集团有限公司")

    # 统一到出现频次最高的写法，而不是被认错的那个
    assert {column["entity_name"] for column in columns} == {"东厦建设开发集团有限公司"}


def test_case2_period_mapping_still_rejects_real_different_companies():
    with pytest.raises(RuntimeError, match="多个企业主体"):
        _validate_sheet_identity(
            [
                {"sheet_name": "资产负债表", "entity_name": "山东尊创置业有限公司"},
                {"sheet_name": "资产负债表", "entity_name": "山东新鸿置业有限公司"},
            ]
        )


def test_case2_period_mapping_normalizes_entity_abbreviations():
    columns = [
        {"sheet_name": "利润表", "entity_name": "东厦"},
        {
            "sheet_name": "利润表",
            "entity_name": "东厦建设开发集团有限公司",
        },
    ]

    _validate_sheet_identity(columns)

    assert {column["entity_name"] for column in columns} == {
        "东厦建设开发集团有限公司"
    }


def test_case2_validation_rejects_all_empty(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "backfill_report.json").write_text(
        json.dumps({"written_cells": 0}), encoding="utf-8"
    )
    (outputs / "case2_filled_schema.json").write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "sheet": "利润表",
                        "items": [
                            {
                                "item_id": "利润表:r5",
                                "fields": {
                                    "C": {
                                        "cell": "C5",
                                        "value_type": "number",
                                        "value": None,
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    ok, message = validate_case2_backfill(tmp_path)

    assert ok is False
    assert "全空" in message


def test_case2_backfill_counts_only_nonempty_and_writes_real_types(tmp_path: Path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()

    wb = Workbook()
    ws = wb.active
    ws.title = "利润表"
    wb.save(inputs / "collection_template.xlsx")
    wb.close()

    filled = {
        "sheets": [
            {
                "sheet": "利润表",
                "items": [
                    {
                        "item_id": "利润表:r4",
                        "evidence_refs": ["ocr_text/report.md"],
                        "fields": {
                            "C": {
                                "cell": "C4",
                                "value_type": "date",
                                "value": "2023-03-31",
                            }
                        },
                    },
                    {
                        "item_id": "利润表:r5",
                        "evidence_refs": ["ocr_text/report.md"],
                        "fields": {
                            "C": {
                                "cell": "C5",
                                "value_type": "number",
                                "value": "1,234.50",
                            },
                            "D": {
                                "cell": "D5",
                                "value_type": "number",
                                "value": None,
                            },
                        },
                    },
                ],
            }
        ]
    }
    (outputs / "case2_filled_schema.json").write_text(
        json.dumps(filled, ensure_ascii=False), encoding="utf-8"
    )

    ok, message = backfill_case2_schema(tmp_path)

    assert ok, message
    report = json.loads((outputs / "backfill_report.json").read_text())
    assert report["target_cells"] == 3
    assert report["written_cells"] == 2
    assert report["empty_cells"] == 1

    check = load_workbook(outputs / "collection_filled.xlsx", data_only=False)
    try:
        assert isinstance(check["利润表"]["C4"].value, datetime)
        assert check["利润表"]["C5"].value == 1234.5
        assert check["利润表"]["D5"].value is None
    finally:
        check.close()

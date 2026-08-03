"""OCR 与 LLM 基础设施的单元测试。

从 test_case2_pipeline.py 拆出，只覆盖与业务场景无关的部分。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.agents import llm as llm_module
from app.agents.llm import LLMDegenerationError, guard_config
from app.services.case2_amounts import is_repaired, parse_amount
from app.services.ocr_runner import ocr_guards_enabled
from app.services.reuse_extract import extract_has_ocr_markdown

def _add_scripts_to_path() -> None:
    import sys

    scripts_dir = str((Path(__file__).resolve().parent.parent / "scripts"))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


_add_scripts_to_path()

_DOUBLE_COLUMN_TABLE = """## 资产负债表 2021-12-31

| 资产     | 行次 |                | 年初数 负债和所有者（或股东）权益 | 行次 | 期末数        | 年初数        |
|----------|------|----------------|--------------------------|------|---------------|---------------|
| 流动资产：|      |                | 流动负债：                | |               |               |
| 货币资金 | 1    | 310,893,340.43 | 134,715,961.79 短期借款   | 31   | 20,000,000.00 | 40,000,000.00 |
| 短期投资 | 2    | 0.00           | 0.00 应付票据             | 32   | 67,113,994.45 | 0.00          |
| 应收票据 | 3    | 699,000.00     | 3,700,000.00 应付账款     | 33   | 381,509,297.36| 1,297,816.00  |
| 应收账款 | 4    | 311,266,236.53 | 125,100,383.26 预收账款   | 34   | 715,641,831.00| 91,232.00     |
| 预付账款 | 5    | 20,634,073.53  | 15,217,548.83 应付职工薪酬 | 35   | 1,468,025.50  | 408,373.29    |
"""

def _split_rows(markdown: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in markdown.splitlines()
        if line.startswith("|") and set(line) - set("|- ")
    ]

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

def test_amount_separator_repair_keeps_normal_values_untouched():
    # 常规写法必须原样通过，重组只在常规解析失败时兜底
    assert parse_amount("457,265,859.05") == 457265859.05
    assert parse_amount("0.00") == 0.0
    assert parse_amount("1.5") == 1.5
    assert parse_amount("(1,234.56)") == -1234.56
    assert is_repaired("457,265,859.05") is False

def test_amount_separator_repair_recovers_ocr_confused_separators():
    # 均取自强制整页 OCR 的真实产物
    assert parse_amount("450,070.190.00") == 450070190.00
    assert parse_amount("1.758,823.768.78") == 1758823768.78
    assert parse_amount("8.785.378,359.75") == 8785378359.75
    assert parse_amount("10.704.829,000.89") == 10704829000.89
    assert is_repaired("1.758,823.768.78") is True

def test_text_layer_guard_flags_only_garbled_amount_pages():
    from text_layer_guard import _is_wellformed

    assert _is_wellformed("399,093,581.74") is True
    assert _is_wellformed("0.00") is True
    assert _is_wellformed("399.093、 581 74") is False
    assert _is_wellformed("767、 7(Xl^00000") is False

def test_text_layer_guard_recognizes_genuinely_broken_amounts():
    """全部取自真实材料文本层的内容。"""
    from text_layer_guard import _is_broken_amount

    for text in (
        "767、 7(Xl^00000",
        "399.093、 581 74",
        "800`955.434 17",
        "457,265,85905",
        "450.070 19000",
    ):
        assert _is_broken_amount(text) is True, text

def test_text_layer_guard_does_not_flag_list_markers_or_dates():
    """回归：初版判据把个人征信报告的列表序号当成畸形金额，误判整份文件。

    误判方向是最坏的——会把一份准确的文本层扔掉换成 OCR 结果。
    """
    from text_layer_guard import _is_broken_amount

    for text in (
        "1.", "2.", "9.", "49",           # 征信报告的列表序号与条目数
        "2023-05-01", "2023.05.01",       # 日期
        "399,093,581.74", "-304,491,654.65", "0.00", "11,390,265,552.64",
    ):
        assert _is_broken_amount(text) is False, text

def test_ocr_guards_scoped_to_case2_by_default():
    """OCR 增强默认只对 case2 生效；case0 材料杂、误判代价高，先不启用。"""
    from app.services.ocr_runner import ocr_guards_enabled

    assert ocr_guards_enabled("case2") is True
    assert ocr_guards_enabled("case0") is False
    assert ocr_guards_enabled("case1") is False

def test_double_column_table_is_split_back_into_two_halves():
    from table_split import split_double_column_tables

    out, reports = split_double_column_tables(_DOUBLE_COLUMN_TABLE)
    rows = _split_rows(out)

    assert len(reports) == 1
    assert reports[0]["columns_after"] == 8
    assert reports[0]["unsplittable_cells"] == []
    # 表头拆成「年初数」和负债侧科目列
    assert rows[0][3] == "年初数"
    assert rows[0][4].startswith("负债和所有者")
    # 数据行：左半年初数与右半科目名各归各位
    货币资金 = rows[2]
    assert 货币资金[2] == "310,893,340.43"
    assert 货币资金[3] == "134,715,961.79"
    assert 货币资金[4] == "短期借款"
    assert 货币资金[6] == "20,000,000.00"

def test_double_column_split_handles_interleaved_header_labels():
    # OCR 有时把两个表头格交错读成「负债和所有者 年初数 (或股东)权益」
    from table_split import split_double_column_tables

    markdown = _DOUBLE_COLUMN_TABLE.replace(
        "年初数 负债和所有者（或股东）权益", "负债和所有者 年初数 (或股东)权益"
    )
    out, reports = split_double_column_tables(markdown)
    rows = _split_rows(out)

    assert len(reports) == 1
    assert rows[0][3] == "年初数"
    assert rows[0][4] == "负债和所有者(或股东)权益"

def test_double_column_split_refuses_cells_it_cannot_resolve():
    # 一格里两个金额说明还发生了跨行错位，不猜：金额侧留空并记入 failures
    from table_split import split_double_column_tables

    markdown = _DOUBLE_COLUMN_TABLE.replace(
        "3,700,000.00 应付账款", "3,700,000.00 1,234.00 应付账款"
    )
    out, reports = split_double_column_tables(markdown)
    rows = _split_rows(out)

    assert reports[0]["unsplittable_cells"] == ["3,700,000.00 1,234.00 应付账款"]
    应收票据 = rows[4]
    assert 应收票据[3] == ""
    assert 应收票据[4] == "3,700,000.00 1,234.00 应付账款"

def test_double_column_split_leaves_ordinary_tables_untouched():
    from table_split import split_double_column_tables

    markdown = """| 项目     | 行次 | 本年累计金额     | 本月金额       |
|----------|------|------------------|----------------|
| 营业收入 | 1    | 1,114,184,729.27 | 260,731,541.20 |
| 营业成本 | 2    | 1,094,459,146.79 | 260,128,870.11 |
"""
    out, reports = split_double_column_tables(markdown)

    assert reports == []
    assert out == markdown

def test_reuse_requires_every_source_to_have_ocr_markdown(tmp_path: Path):
    """OCR 中途失败留下的残缺产物不能被当成「已 OCR」而跳过重跑。

    多文件任务中途 OOM 会只留下部分 md，同材料的新任务命中它就整个跳过 OCR，
    缺的那几份再也补不上。
    """
    from app.services.reuse_extract import extract_has_ocr_markdown

    src = tmp_path / "sources"
    src.mkdir()
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (src / name).write_bytes(b"%PDF-1.4\n")
    ocr = tmp_path / "ocr_text" / "sources"
    ocr.mkdir(parents=True)

    (ocr / "a.pdf.md").write_text("x", encoding="utf-8")
    assert extract_has_ocr_markdown(tmp_path) is False   # 残缺

    (ocr / "b.pdf.md").write_text("x", encoding="utf-8")
    assert extract_has_ocr_markdown(tmp_path) is False   # 仍残缺

    (ocr / "c.pdf.md").write_text("x", encoding="utf-8")
    assert extract_has_ocr_markdown(tmp_path) is True    # 齐了才算数

def test_ocr_meta_fingerprint_invalidates_when_code_or_switches_change(tmp_path: Path):
    """OCR 代码或开关变了，历史 ocr_text 不能再被复用。

    复用只按材料 md5 匹配，不看产物是哪版代码跑的；改完 OCR 链路后同材料的
    新任务会静默复用旧 markdown，日志只有一句 OCR skipped，产物上看不出来。
    """
    import ocr_meta

    ocr_dir = tmp_path / "ocr_text"
    switches = {"text_layer_guard": True, "table_split": True}

    assert ocr_meta.meta_matches(ocr_dir, switches) is False  # 没有 meta 一律不复用

    ocr_meta.write_meta(ocr_dir, switches)
    assert ocr_meta.meta_matches(ocr_dir, switches) is True

    # 开关变了就失效
    assert ocr_meta.meta_matches(ocr_dir, {"text_layer_guard": False, "table_split": True}) is False

    # 代码变了就失效（直接改存档里的指纹等价于改代码）
    import json

    meta_path = ocr_dir / ocr_meta.META_NAME
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["code"] = "0" * 16
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    assert ocr_meta.meta_matches(ocr_dir, switches) is False

def test_ocr_code_fingerprint_is_stable_and_covers_ocr_scripts():
    import ocr_meta

    assert ocr_meta.code_fingerprint() == ocr_meta.code_fingerprint()
    assert "table_split.py" in ocr_meta._FINGERPRINT_SOURCES
    assert "text_layer_guard.py" in ocr_meta._FINGERPRINT_SOURCES

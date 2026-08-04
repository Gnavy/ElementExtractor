"""Smoke tests for LangGraph agent wiring (no live LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.graphs import build_case1_graph, build_case2_graph, build_general_graph
from app.agents.llm import scene_for_task_kind, should_skip_agent, structured_llm
from app.agents.nodes.common.load_meta import load_meta_node
from app.agents.nodes.general.classify import parse_extract_schema
from app.agents.nodes.general.extract import _merge_query_terms, extract_one_field_node
from app.agents.schemas.case1_row import Case1GroupFill, Case1RowFill
from app.agents.schemas.classification import ClassificationResult
from app.agents.schemas.case2_item import Case2BatchFill, Case2ItemFill
from app.agents.schemas.extraction import (
    FieldExtractResult,
    FieldQueryTerms,
    GradeEvidence,
    QueryExpansionResult,
)


def test_graphs_compile():
    assert build_general_graph() is not None
    assert build_case1_graph() is not None
    assert build_case2_graph() is not None


def test_load_meta_node(tmp_path: Path):
    meta = {
        "task_id": "t1",
        "task_kind": "case1",
        "classification_basis": "x",
        "extract_schema": "{}",
    }
    (tmp_path / ".task-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    out = load_meta_node({"extract_root": str(tmp_path), "task_kind": "case1"})
    assert out["task_id"] == "t1"
    assert out["meta"]["task_kind"] == "case1"


def test_parse_extract_schema():
    fields = parse_extract_schema(
        {
            "extract_schema": json.dumps(
                {"fields": [{"name": "债务人", "description": "名称", "type": "text"}]}
            )
        }
    )
    assert len(fields) == 1
    assert fields[0]["name"] == "债务人"


def test_merge_query_terms_keeps_description_and_llm():
    terms = _merge_query_terms(
        field_name="营业执照-文书名称",
        description="从债务人营业执照提取企业名称",
        llm_terms=["统一社会信用代码", "公司名称", "名称"],
        doc_hints=["营业执照"],
    )
    assert "营业执照" in terms or any("营业" in t for t in terms)
    assert any("债务" in t or "债务人" in t for t in terms)
    assert "名称" not in terms  # 过宽泛词应过滤
    assert "统一社会信用代码" in terms or any("信用" in t for t in terms)


def test_null_field_retries_with_exact_field_context(monkeypatch, tmp_path: Path):
    """宽泛检索漏证时，只对完整字段名命中的空值补试一次。"""
    from app.agents.nodes.general import extract as extract_module

    collected_keywords: list[list[str]] = []
    extraction_messages = []

    def fake_collect(_root, *, keywords=None, **_kwargs):
        terms = list(keywords or [])
        collected_keywords.append(terms)
        if terms == ["统一社会信用代码"]:
            return "公司名称：浙江文承置业有限公司\n统一社会信用代码：91330782MADABA98X1"
        return "债务人：浙江文承置业有限公司"

    class FakeExtractLlm:
        def invoke(self, messages):
            extraction_messages.append(messages)
            if len(extraction_messages) == 1:
                return FieldExtractResult(
                    field_name="统一社会信用代码",
                    value=None,
                    confidence="low",
                )
            return FieldExtractResult(
                field_name="统一社会信用代码",
                value="91330782MADABA98X1",
                confidence="high",
                source_files=["ocr_text/project.docx.md"],
                evidence=[
                    {
                        "file": "ocr_text/project.docx.md",
                        "quote": "统一社会信用代码：91330782MADABA98X1",
                    }
                ],
            )

    class FakeGradeLlm:
        def invoke(self, _messages):
            return GradeEvidence(grounded=False, reason="需要重新取证")

    def fake_structured_llm(schema, **_kwargs):
        return FakeExtractLlm() if schema is FieldExtractResult else FakeGradeLlm()

    monkeypatch.setattr(extract_module, "collect_ocr_snippets", fake_collect)
    monkeypatch.setattr(extract_module, "structured_llm", fake_structured_llm)

    result = extract_one_field_node(
        {
            "extract_root": str(tmp_path),
            "task_id": "t1",
            "field": {
                "name": "统一社会信用代码",
                "description": "18 位统一社会信用代码",
                "type": "string",
                "query_terms": ["统一", "登记"],
            },
        }
    )

    item = result["extracted_fields"]["统一社会信用代码"]
    assert item["value"] == "91330782MADABA98X1"
    assert collected_keywords == [["统一", "登记"], ["统一社会信用代码"]]
    assert len(extraction_messages) == 3
    assert "91330782MADABA98X1" in extraction_messages[1][1][1]
    assert "91330782MADABA98X1" in extraction_messages[2][1][1]
    assert "已精确检索重试" in "\n".join(result["log_lines"])
    assert "精确检索重试结果: 统一社会信用代码=91330782MADABA98X1" in "\n".join(
        result["log_lines"]
    )


def test_null_field_skips_retry_without_exact_field_match(monkeypatch, tmp_path: Path):
    """材料没有完整字段名时不追加模型调用。"""
    from app.agents.nodes.general import extract as extract_module

    calls = 0

    def fake_collect(_root, *, keywords=None, **_kwargs):
        return "债务人：浙江文承置业有限公司"

    class FakeExtractLlm:
        def invoke(self, _messages):
            nonlocal calls
            calls += 1
            return FieldExtractResult(
                field_name="统一社会信用代码",
                value=None,
                confidence="low",
            )

    monkeypatch.setattr(extract_module, "collect_ocr_snippets", fake_collect)
    monkeypatch.setattr(
        extract_module,
        "structured_llm",
        lambda _schema, **_kwargs: FakeExtractLlm(),
    )

    result = extract_one_field_node(
        {
            "extract_root": str(tmp_path),
            "field": {
                "name": "统一社会信用代码",
                "description": "18 位统一社会信用代码",
                "query_terms": ["统一", "登记"],
            },
        }
    )

    assert calls == 1
    assert result["extracted_fields"]["统一社会信用代码"]["value"] is None
    assert len(result["log_lines"]) == 1


def test_query_expansion_schema():
    q = QueryExpansionResult(
        fields=[
            FieldQueryTerms(
                field_name="注册资本",
                query_terms=["注册资本", "实收资本"],
                doc_hints=["营业执照"],
            )
        ]
    )
    assert q.fields[0].field_name == "注册资本"


def test_pydantic_schemas():
    c = ClassificationResult(task_id="t", categories=[])
    assert c.task_id == "t"
    g = Case1GroupFill(
        indicator_name="增信",
        rows=[Case1RowFill(row=10, choice="是", remark="见尽调报告")],
    )
    assert g.rows[0].choice == "是"
    b = Case2BatchFill(
        items=[Case2ItemFill(item_id="资产负债表:r6", fields={"C": 1.0})]
    )
    assert b.items[0].item_id.endswith("r6")


def test_should_skip_agent_respects_env(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "skip_agent", True)
    monkeypatch.setattr(settings, "skip_claude", False)
    assert should_skip_agent() is True
    monkeypatch.setattr(settings, "skip_agent", False)
    monkeypatch.setattr(settings, "skip_claude", True)
    assert should_skip_agent() is True
    monkeypatch.setattr(settings, "skip_agent", False)
    monkeypatch.setattr(settings, "skip_claude", False)
    assert should_skip_agent() is False


def _scene_models(monkeypatch, *, general="", case1="", case2=""):
    """三个场景经 structured_llm 各自实际拿到的模型名"""
    from app.agents import llm as llm_module
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_model", "default-model")
    monkeypatch.setattr(settings, "llm_model_general", general)
    monkeypatch.setattr(settings, "llm_model_case1", case1)
    monkeypatch.setattr(settings, "llm_model_case2", case2)

    real_get_chat_model = llm_module.get_chat_model
    picked: list[str] = []

    def spy(**kwargs):
        model = real_get_chat_model(**kwargs)
        picked.append(model.model_name)
        return model

    spy.cache_clear = real_get_chat_model.cache_clear
    monkeypatch.setattr(llm_module, "get_chat_model", spy)
    llm_module.clear_chat_model_cache()
    try:
        for scene in ("general", "case1", "case2"):
            llm_module.structured_llm(ClassificationResult, scene=scene)
        return tuple(picked)
    finally:
        llm_module.clear_chat_model_cache()


def test_scene_model_falls_back_to_default(monkeypatch):
    # 三个场景都不配时行为与按场景配置前一致
    assert _scene_models(monkeypatch) == ("default-model",) * 3


def test_scene_model_overrides_default(monkeypatch):
    assert _scene_models(monkeypatch, case1="model-a") == (
        "default-model",
        "model-a",
        "default-model",
    )


def test_scene_models_are_independent(monkeypatch):
    assert _scene_models(monkeypatch, case1="model-a", case2="model-b") == (
        "default-model",
        "model-a",
        "model-b",
    )


def test_unknown_scene_fails_fast():
    # 场景名写错时立即报错，不静默退回默认模型
    # 用 case0 当反例：它是注释里对通用场景的口语称呼，不是有效场景键
    with pytest.raises(AttributeError):
        structured_llm(ClassificationResult, scene="case0")


def test_guard_config_keeps_inherited_callbacks():
    """显式传 config 不能顶掉图上的 callbacks，否则用量统计收不到这些调用"""
    from typing import Any

    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langgraph.graph import END, START, StateGraph

    from app.agents.llm import _WhitespaceRunGuard, guard_config

    class Spy(BaseCallbackHandler):
        def __init__(self) -> None:
            self.starts = 0

        def on_chat_model_start(self, *a: Any, **k: Any) -> None:
            self.starts += 1

    guard_counts: list[int] = []

    def node(_state: dict[str, Any]) -> dict[str, Any]:
        cfg = guard_config()
        handlers = getattr(cfg.get("callbacks"), "handlers", cfg.get("callbacks")) or []
        guard_counts.append(sum(isinstance(h, _WhitespaceRunGuard) for h in handlers))
        FakeListChatModel(responses=["ok"]).invoke("hi", config=cfg)
        return {"done": True}

    g = StateGraph(dict)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile()

    spy = Spy()
    app.invoke({}, config={"callbacks": [spy]})
    assert spy.starts == 1

    # 每次 invoke 只挂一个退化探测，不因继承而累积
    app.invoke({}, config={"callbacks": [Spy()]})
    assert set(guard_counts) == {1}


def test_empty_token_usage_still_writes_output(tmp_path: Path):
    """调用失败前没有 usage 时，也要留下可排查的标准产物。"""
    from app.agents import runner as runner_module

    class EmptyUsage:
        usage_metadata = {}

    class CaptureLogger:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def log(self, line: str) -> None:
            self.lines.append(line)

    logger = CaptureLogger()
    runner_module._dump_token_usage(
        tmp_path,
        EmptyUsage(),
        task_id="t1",
        task_kind="case1",
        logger=logger,
    )

    payload = json.loads((tmp_path / "token_usage.json").read_text(encoding="utf-8"))
    assert payload == {
        "task_id": "t1",
        "task_kind": "case1",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "by_model": {},
        "usage_available": False,
    }
    assert any("未返回 usage" in line for line in logger.lines)


def test_task_kind_maps_to_scene():
    # general 图的三种 task_kind 共用 general 一个键
    assert scene_for_task_kind("general") == "general"
    assert scene_for_task_kind("classification") == "general"
    assert scene_for_task_kind("extraction") == "general"
    assert scene_for_task_kind(None) == "general"
    assert scene_for_task_kind("case1") == "case1"
    assert scene_for_task_kind("case2") == "case2"
    # 规范化方式与 runner._select_builder 一致（只 lower、不 strip）
    assert scene_for_task_kind("CASE1") == "case1"


def test_agent_log_records_scene_model(monkeypatch, tmp_path: Path):
    """任务日志必须写实际生效的模型，写成 LLM_MODEL 会把排查带偏"""
    from app.agents import runner as runner_module
    from app.config import settings

    monkeypatch.setattr(settings, "llm_model", "default-model")
    monkeypatch.setattr(settings, "llm_model_general", "")
    monkeypatch.setattr(settings, "llm_model_case1", "case1-model")
    monkeypatch.setattr(settings, "llm_model_case2", "")
    monkeypatch.setattr(settings, "skip_agent", True)  # 只跑到日志那步就返回

    def _first_line(task_kind):
        out = tmp_path / task_kind
        runner_module.run_agent(tmp_path, out, task_id="t1", task_kind=task_kind)
        return (out / "agent.log").read_text(encoding="utf-8").splitlines()[0]

    assert "model=case1-model" in _first_line("case1")
    # 没单配的场景仍记录默认模型
    assert "model=default-model" in _first_line("case2")
    assert "model=default-model" in _first_line("extraction")

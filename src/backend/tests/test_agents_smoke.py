"""Smoke tests for LangGraph agent wiring (no live LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.graphs import build_case1_graph, build_case2_graph, build_general_graph
from app.agents.llm import scene_for_task_kind, should_skip_agent, structured_llm
from app.agents.nodes.common.load_meta import load_meta_node
from app.agents.nodes.general.classify import parse_extract_schema
from app.agents.nodes.general.extract import _merge_query_terms
from app.agents.schemas.case1_row import Case1GroupFill, Case1RowFill
from app.agents.schemas.classification import ClassificationResult
from app.agents.schemas.case2_item import Case2BatchFill, Case2ItemFill
from app.agents.schemas.extraction import FieldQueryTerms, QueryExpansionResult


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

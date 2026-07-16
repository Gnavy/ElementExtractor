"""Smoke tests for LangGraph agent wiring (no live LLM calls)."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.graphs import build_case1_graph, build_case2_graph, build_general_graph
from app.agents.llm import should_skip_agent
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

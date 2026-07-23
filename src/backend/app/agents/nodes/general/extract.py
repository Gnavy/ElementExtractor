from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.agents.llm import structured_llm
from app.agents.nodes.general.classify import parse_extract_schema
from app.agents.prompts import general as prompts
from app.agents.schemas.extraction import (
    FieldExtractResult,
    GradeEvidence,
    QueryExpansionResult,
)
from app.agents.tools.context import (
    build_shared_material_context,
    collect_ocr_snippets,
    expand_keywords,
    write_json,
)
from app.agents.tools.path_remap import remap_extracted_payload

logger = logging.getLogger(__name__)

_GENERIC_TERMS = {
    "企业",
    "名称",
    "是否",
    "摘要",
    "结论",
    "清单",
    "信息",
    "材料",
    "字段",
    "内容",
    "相关",
    "证明",
    "区域",
}


def prepare_fields_node(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("meta") or {}
    fields = parse_extract_schema(meta)
    root = Path(state["extract_root"])
    task_id = state.get("task_id") or meta.get("task_id") or ""

    # 按用户描述批量扩展检索词，再挂到各字段
    fields, expand_note = _attach_query_expansion(fields, task_id=task_id, root=root)

    material_context = build_shared_material_context(root, max_total_chars=28000)
    return {
        "schema_fields": fields,
        "extracted_fields": state.get("extracted_fields") or {},
        "fields_to_retry": [],
        "material_context": material_context,
        "log_lines": [
            f"待抽取字段数={len(fields)}",
            expand_note,
            f"共享材料上下文约 {len(material_context)} 字",
        ],
        "progress": f"准备抽取 {len(fields)} 个字段",
    }


def _attach_query_expansion(
    fields: list[dict[str, Any]],
    *,
    task_id: str,
    root: Path,
) -> tuple[list[dict[str, Any]], str]:
    if not fields:
        return fields, "检索词扩展：无字段"

    payload_fields = [
        {
            "name": str(f.get("name") or ""),
            "description": str(f.get("description") or ""),
            "type": str(f.get("type") or "text"),
        }
        for f in fields
    ]

    expanded_map: dict[str, dict[str, list[str]]] = {}
    note = "检索词扩展：规则兜底"
    try:
        llm = structured_llm(QueryExpansionResult)
        result: QueryExpansionResult = llm.invoke(
            [
                ("system", prompts.EXPAND_QUERY_SYSTEM),
                (
                    "human",
                    prompts.EXPAND_QUERY_USER.format(
                        task_id=task_id,
                        fields_json=json.dumps(
                            payload_fields, ensure_ascii=False, indent=2
                        ),
                    ),
                ),
            ]
        )
        for item in result.fields or []:
            name = (item.field_name or "").strip()
            if not name:
                continue
            expanded_map[name] = {
                "query_terms": [
                    t.strip() for t in (item.query_terms or []) if t and str(t).strip()
                ],
                "doc_hints": [
                    t.strip() for t in (item.doc_hints or []) if t and str(t).strip()
                ],
            }
        note = f"检索词扩展：LLM 覆盖 {len(expanded_map)}/{len(fields)} 字段"
    except Exception as exc:  # noqa: BLE001 — 扩展失败不阻断抽取
        logger.warning("query expansion LLM failed, using fallback: %s", exc)
        note = f"检索词扩展失败，已规则兜底（{exc}）"

    out: list[dict[str, Any]] = []
    dump: dict[str, Any] = {}
    for f in fields:
        name = str(f.get("name") or "")
        desc = str(f.get("description") or "")
        llm_terms = expanded_map.get(name) or {}
        terms = _merge_query_terms(
            field_name=name,
            description=desc,
            llm_terms=llm_terms.get("query_terms") or [],
            doc_hints=llm_terms.get("doc_hints") or [],
        )
        enriched = dict(f)
        enriched["query_terms"] = terms
        enriched["doc_hints"] = list(llm_terms.get("doc_hints") or [])[:6]
        out.append(enriched)
        dump[name] = {
            "description": desc,
            "query_terms": terms,
            "doc_hints": enriched["doc_hints"],
        }

    try:
        write_json(root / "outputs" / "field_query_terms.json", dump)
    except OSError:
        pass
    return out, note


def _merge_query_terms(
    *,
    field_name: str,
    description: str,
    llm_terms: list[str],
    doc_hints: list[str],
) -> list[str]:
    """合并 LLM 扩展词与字段名/描述切词；过滤过宽泛词。"""
    seed = [field_name] + _split_desc(description)[:12] + list(llm_terms) + list(doc_hints)
    expanded = expand_keywords(seed)
    out: list[str] = []
    seen: set[str] = set()
    for t in expanded:
        key = t.strip().lower()
        if len(key) < 2 or key in _GENERIC_TERMS or key in seen:
            continue
        seen.add(key)
        out.append(t.strip())
        if len(out) >= 20:
            break
    return out


def _split_desc(desc: str) -> list[str]:
    return [w for w in re.split(r"[,，、/;；\s]+", desc or "") if w.strip()]


def extract_one_field_node(state: dict[str, Any]) -> dict[str, Any]:
    """Worker node invoked via Send for a single field."""
    root = Path(state["extract_root"])
    field = state.get("field") or {}
    field_name = str(field.get("name") or "")
    desc = str(field.get("description") or "")
    ftype = str(field.get("type") or "text")
    task_id = state.get("task_id") or ""
    classification_summary = state.get("classification_summary") or ""

    shared = (state.get("context_snippets") or "").strip()
    # 优先用 prepare_fields 挂好的扩展词；否则现场兜底（含描述切词）
    keywords = list(field.get("query_terms") or [])
    if not keywords:
        keywords = _merge_query_terms(
            field_name=field_name,
            description=desc,
            llm_terms=[],
            doc_hints=list(field.get("doc_hints") or []),
        )
    focused = collect_ocr_snippets(
        root,
        keywords=keywords,
        max_files=8,
        max_chars_per_file=3000,
        max_total_chars=12000,
    )
    if shared and focused and focused not in shared:
        context = (
            "【字段相关材料（优先）】\n"
            + focused
            + "\n\n【其他材料摘要】\n"
            + shared[:16000]
        )
    else:
        context = focused or shared or "（无材料上下文）"

    # 描述为空时也明确提示，避免模型只靠字段名臆测
    desc_for_prompt = desc.strip() or "（用户未填写描述；请仅依据字段名在材料中寻找，无把握则 value=null）"

    llm = structured_llm(FieldExtractResult)
    result: FieldExtractResult = llm.invoke(
        [
            ("system", prompts.EXTRACT_FIELD_SYSTEM),
            (
                "human",
                prompts.EXTRACT_FIELD_USER.format(
                    task_id=task_id,
                    field_name=field_name,
                    field_description=desc_for_prompt,
                    field_type=ftype,
                    classification_summary=classification_summary,
                    context=context,
                ),
            ),
        ]
    )

    entry = {
        "value": result.value,
        "confidence": result.confidence or "medium",
        "source_files": result.source_files or [],
        "evidence": [e.model_dump() for e in (result.evidence or [])],
        "notes": result.notes,
    }
    if ftype == "image":
        entry["_crop"] = {
            "bbox": result.crop_bbox,
            "page": result.crop_page,
            "source": result.crop_source,
        }

    # Optional evidence grade + single retry（仅当有 evidence 时）
    retry_count = int(state.get("retry_count") or 0)
    if result.value not in (None, "") and result.evidence and retry_count < 1:
        grader = structured_llm(GradeEvidence)
        grade: GradeEvidence = grader.invoke(
            [
                ("system", prompts.GRADE_EVIDENCE_SYSTEM),
                (
                    "human",
                    prompts.GRADE_EVIDENCE_USER.format(
                        field_name=field_name,
                        value=repr(result.value),
                        evidence=str([e.model_dump() for e in (result.evidence or [])]),
                    ),
                ),
            ]
        )
        if not grade.grounded:
            result2: FieldExtractResult = llm.invoke(
                [
                    (
                        "system",
                        prompts.EXTRACT_FIELD_SYSTEM
                        + "\n上次结果未通过证据校验，请重新严格取证；"
                        "若材料确实没有该信息则 value=null。"
                        "仍必须严格遵循用户对要素的「描述」。",
                    ),
                    (
                        "human",
                        prompts.EXTRACT_FIELD_USER.format(
                            task_id=task_id,
                            field_name=field_name,
                            field_description=desc_for_prompt
                            + f"\n质检意见: {grade.reason}",
                            field_type=ftype,
                            classification_summary=classification_summary,
                            context=context,
                        ),
                    ),
                ]
            )
            entry = {
                "value": result2.value,
                "confidence": result2.confidence or "low",
                "source_files": result2.source_files or [],
                "evidence": [e.model_dump() for e in (result2.evidence or [])],
                "notes": (result2.notes or "") + f"（证据复核: {grade.reason}）",
            }
            if ftype == "image":
                entry["_crop"] = {
                    "bbox": result2.crop_bbox,
                    "page": result2.crop_page,
                    "source": result2.crop_source,
                }

    if ftype == "image":
        # 图片路径必须由裁剪节点在文件实际生成后写入，避免模型返回尚不存在的预期路径
        entry["value"] = None

    return {
        "extracted_fields": {field_name: entry},
        "log_lines": [
            f"已抽取字段: {field_name}={_brief(entry.get('value'))}"
        ],
        "progress": f"正在抽取字段：{field_name}",
    }


def _brief(v: Any, n: int = 40) -> str:
    if v is None:
        return "null"
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def merge_extracted_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    meta = state.get("meta") or {}
    task_id = state.get("task_id") or meta.get("task_id") or ""
    fields = dict(state.get("extracted_fields") or {})
    clean: dict[str, Any] = {}
    nonempty = 0
    for name, val in fields.items():
        if not isinstance(val, dict):
            continue
        item = {k: v for k, v in val.items() if k != "_crop"}
        clean[name] = item
        if item.get("value") not in (None, ""):
            nonempty += 1
    payload = {"task_id": task_id, "fields": clean}
    payload = remap_extracted_payload(payload, root)
    write_json(root / "outputs" / "extracted.json", payload)
    nonempty = sum(
        1
        for v in (payload.get("fields") or {}).values()
        if isinstance(v, dict) and v.get("value") not in (None, "")
    )
    return {
        "log_lines": [
            f"已写入 extracted.json（字段数={len(clean)}，有值={nonempty}）"
        ],
        "progress": "要素抽取完成",
    }

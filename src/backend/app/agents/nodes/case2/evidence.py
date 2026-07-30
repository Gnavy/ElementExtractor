from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from app.agents.llm import fallback_max_tokens, guard_config, structured_llm
from app.agents.prompts import case2 as prompts
from app.agents.schemas.case2_item import Case2ChunkEvidence, Case2PeriodMap
from app.agents.tools.context import write_json
from app.services.case2_review import add_review_flags


_CHUNK_CHARS = 7000
_CHUNK_OVERLAP = 800
# 证据抽取默认不设输出上限，由 llm.guard_config() 的退化探测兜底；
# 仅在非流式（探测器失效）时用下面这个宽松上限保底
_EVIDENCE_FALLBACK_MAX_TOKENS = 16384
_PERIOD_MAP_MAX_TOKENS = 4096
_NULL_TEXT = {"", "null", "none", "nil", "n/a", "na", "未披露", "未找到"}
_DATE_RE = re.compile(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?")
_IMAGE_MARKER_RE = re.compile(r"<!--\s*image\s*-->", flags=re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[\s:：()（）\-_/、，。·]+")
_LABEL_PREFIX_RE = re.compile(r"^(?:其中|加|减|其中加|其中减)[:：]?\s*")
_FINANCIAL_HEADER_RE = re.compile(
    r"(资产负债表|利润表|现金流量表|"
    r"20\d{2}(?:[-/.年]\d{1,2})?|"
    r"编制单位|单位[:：]|"
    r"期末(?:余额|数)|年初(?:余额|数)|"
    r"本年累计金额|本月金额|本期金额|上期金额)"
)
_STATEMENT_NAMES = ("资产负债表", "利润表", "现金流量表")
# 短名字差一个字往往是两家公司（甲公司/乙公司），只在长名字上认 OCR 错字
_ENTITY_FUZZY_MIN_LEN = 6
_OPENING_PERIOD_RE = re.compile(r"(年初|期初|上年年末|上年期末)")
_CLOSING_PERIOD_RE = re.compile(r"(期末|年末)")


def _normalize_text(value: Any) -> str:
    return _NON_WORD_RE.sub("", str(value or "")).lower()


def _normalize_scope(value: Any) -> str:
    text = _normalize_text(value)
    if "合并" in text:
        return "合并"
    if "母公司" in text:
        return "母公司"
    if text in {"单体", "单户"}:
        return "单体"
    return ""


def _canonical_entity_name(values: list[Any], *, preferred: Any = "") -> str:
    """把同一主体的多种写法归并成一个代表名；确属不同主体时返回空串。"""
    names = sorted(
        {
            str(value or "").strip()
            for value in values
            if _normalize_text(value)
        },
        # 按归一化长度降序，同长按字面排序，避免 set 迭代顺序带来的不确定
        key=lambda value: (-len(_normalize_text(value)), value),
    )
    if not names:
        return ""
    # 优先用出现频次最高的写法当代表名，免得代表名是被 OCR 认错的那个。
    # 注意要拿每个变体去比代表名，不能变体之间两两比——两个各错一个字的
    # 写法彼此会差两个字，那样同一主体反而会被判成不同主体。
    text = str(preferred or "").strip()
    if text and all(_entity_match_kind(text, name) != "none" for name in names):
        return text
    longest = names[0]
    normalized_longest = _normalize_text(longest)
    if all(_normalize_text(name) in normalized_longest for name in names[1:]):
        return longest
    if all(_entity_match_kind(longest, name) != "none" for name in names[1:]):
        return longest
    return ""


def _dominant_entity_name(catalog: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for fact in catalog.get("facts") or []:
        name = str(fact.get("entity_name") or "").strip()
        if _normalize_text(name):
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return sorted(
        counts.items(), key=lambda kv: (-kv[1], -len(_normalize_text(kv[0])), kv[0])
    )[0][0]


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, lc in enumerate(left, start=1):
        current = [i]
        for j, rc in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (lc != rc),
                )
            )
        previous = current
    return previous[-1]


def _entity_key(value: Any) -> str:
    """比对用的主体名：去掉标点和「（并）」这类口径批注，只留名字本身"""
    text = re.sub(r"[(（][^)）]{0,6}[)）]", "", str(value or ""))
    return _normalize_text(text)


def _entity_match_kind(left: Any, right: Any) -> str:
    """返回 exact / fuzzy / none。

    fuzzy 只覆盖扫描件 OCR 认错一两个字的情况（东厦→东度），判定条件是
    名字足够长、长度几乎相同、且只差一个字符。刻意不放宽到「相似即同一」：
    「XX集团有限公司」与「XX有限公司」常常是母子公司，「甲公司」与「乙公司」
    也只差一个字，混填违反业务口径。
    """
    left_key = _entity_key(left)
    right_key = _entity_key(right)
    if not left_key or not right_key:
        return "exact"
    if left_key in right_key or right_key in left_key:
        return "exact"
    if (
        min(len(left_key), len(right_key)) >= _ENTITY_FUZZY_MIN_LEN
        and abs(len(left_key) - len(right_key)) <= 1
        and _edit_distance(left_key, right_key) <= 1
    ):
        return "fuzzy"
    return "none"


def _entity_names_compatible(left: Any, right: Any) -> bool:
    return _entity_match_kind(left, right) != "none"


def _fuzzy_entity_pairs(catalog: dict[str, Any]) -> list[tuple[str, str]]:
    """列出被判为「同一主体的 OCR 变体」的名字对，供人工复核"""
    names = _entity_variants(catalog)
    pairs: list[tuple[str, str]] = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if _entity_match_kind(left, right) == "fuzzy":
                pairs.append((left, right))
    return pairs


def _entity_variants(catalog: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(entry.get("entity_name") or "").strip()
            for entry in catalog.get("facts") or []
            if _normalize_text(entry.get("entity_name"))
        }
    )


def _normalize_statement(value: Any) -> str:
    text = _normalize_text(value)
    for name in _STATEMENT_NAMES:
        if _normalize_text(name) in text:
            return name
    return text


def _sidecar_text(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    lines: list[str] = []
    last_page: Any = None
    for cell in data.get("cells") or []:
        text = str(cell.get("text") or "").strip()
        if not text:
            continue
        page = cell.get("page")
        if page != last_page:
            lines.append(f"\n## OCR Page {page or '?'}")
            last_page = page
        lines.append(text)
    return "\n".join(lines).strip()


def _sidecar_page_headers(path: Path) -> dict[int, list[str]]:
    """提取每页顶部的财务报表页眉，补足 Markdown 序列化遗漏。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    headers: dict[int, list[str]] = {}
    seen: dict[int, set[str]] = {}
    for cell in data.get("cells") or []:
        page = cell.get("page")
        text = str(cell.get("text") or "").strip()
        if not isinstance(page, int) or not text or not _FINANCIAL_HEADER_RE.search(text):
            continue
        bbox = cell.get("bbox")
        if (
            isinstance(bbox, list)
            and len(bbox) >= 2
            and isinstance(bbox[1], (int, float))
            and bbox[1] > 0.28
        ):
            continue
        normalized = _normalize_text(text)
        page_seen = seen.setdefault(page, set())
        if normalized in page_seen:
            continue
        page_seen.add(normalized)
        headers.setdefault(page, []).append(text)
    return headers


def _supplement_page_header(text: str, header_lines: list[str]) -> str:
    normalized_text = _normalize_text(text)
    missing = [
        line
        for line in header_lines
        if _normalize_text(line) not in normalized_text
    ]
    if not missing:
        return text
    return "## OCR 页眉补充\n" + "\n".join(missing) + "\n\n" + text


def _usable_markdown(text: str) -> bool:
    body = _IMAGE_MARKER_RE.sub("", text)
    return len(body.strip()) >= 80


def _split_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            newline = text.rfind("\n", start + max_chars // 2, hard_end)
            if newline > start:
                end = newline
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _markdown_units(text: str) -> list[tuple[int | None, str]]:
    """扫描 PDF 的 image marker 通常对应页；保留该边界再做字符分块。"""
    if not _IMAGE_MARKER_RE.search(text):
        return [(None, text)]
    units: list[tuple[int | None, str]] = []
    for page, part in enumerate(_IMAGE_MARKER_RE.split(text), start=0):
        body = part.strip()
        if not body:
            continue
        units.append((page if page > 0 else None, body))
    return units or [(None, text)]


def build_case2_ocr_chunks(
    extract_root: Path,
    *,
    max_chars: int = _CHUNK_CHARS,
    overlap: int = _CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """读取全部 OCR 文本并分块，不按关键词丢弃材料。"""
    ocr_dir = extract_root / "ocr_text"
    if not ocr_dir.is_dir():
        return []

    chunks: list[dict[str, Any]] = []
    consumed_sidecars: set[Path] = set()
    for md_path in sorted(ocr_dir.rglob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sidecar = Path(str(md_path.with_suffix("")) + ".ocr_cells.json")
        page_headers: dict[int, list[str]] = {}
        if not _usable_markdown(text) and sidecar.is_file():
            fallback = _sidecar_text(sidecar)
            if fallback:
                text = fallback
                consumed_sidecars.add(sidecar)
        elif sidecar.is_file():
            page_headers = _sidecar_page_headers(sidecar)
        if not text.strip():
            continue
        source_ref = md_path.relative_to(extract_root).as_posix()
        source_relative = md_path.relative_to(ocr_dir).as_posix().removesuffix(".md")
        for page, unit in _markdown_units(text):
            if page is not None:
                unit = _supplement_page_header(
                    unit,
                    page_headers.get(page) or [],
                )
            pieces = _split_text(unit, max_chars=max_chars, overlap=overlap)
            for index, piece in enumerate(pieces, start=1):
                chunks.append(
                    {
                        "source_ref": source_ref,
                        "source_name": md_path.name.removesuffix(".md"),
                        "source_relative": source_relative.removeprefix("sources/"),
                        "page": page,
                        "part_index": index,
                        "part_count": len(pieces),
                        "text": piece,
                    }
                )

    for sidecar in sorted(ocr_dir.rglob("*.ocr_cells.json")):
        if sidecar in consumed_sidecars:
            continue
        md_path = Path(str(sidecar)[: -len(".ocr_cells.json")] + ".md")
        if md_path.is_file():
            continue
        text = _sidecar_text(sidecar)
        if not text:
            continue
        source_ref = sidecar.relative_to(extract_root).as_posix()
        source_relative = (
            sidecar.relative_to(ocr_dir)
            .as_posix()
            .removesuffix(".ocr_cells.json")
            .removeprefix("sources/")
        )
        pieces = _split_text(text, max_chars=max_chars, overlap=overlap)
        for index, piece in enumerate(pieces, start=1):
            chunks.append(
                {
                    "source_ref": source_ref,
                    "source_name": sidecar.name.removesuffix(".ocr_cells.json"),
                    "source_relative": source_relative,
                    "page": None,
                    "part_index": index,
                    "part_count": len(pieces),
                    "text": piece,
                }
            )
    return chunks


def _target_items(schema: dict[str, Any]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for sheet in schema.get("sheets") or []:
        sheet_name = str(sheet.get("sheet") or sheet.get("name") or "")
        for item in sheet.get("items") or []:
            item_id = str(item.get("item_id") or "")
            if not item_id:
                continue
            targets.append(
                {
                    "item_id": item_id,
                    "sheet_name": sheet_name,
                    "statement_name": _normalize_statement(sheet_name),
                    "label": str(item.get("label") or ""),
                    "meaning": str(item.get("meaning") or ""),
                }
            )
    return targets


def _label_variants(label: str) -> set[str]:
    variants = {_normalize_text(label)}
    stripped = _LABEL_PREFIX_RE.sub("", label).strip()
    variants.add(_normalize_text(stripped))
    return {value for value in variants if len(value) >= 2}


def _statement_headings(text: str) -> set[str]:
    """识别短报表标题行，避免命中“资产负债表日”等附注正文。"""
    headings: set[str] = set()
    for raw_line in text.splitlines():
        line = _normalize_text(raw_line)
        if not line or len(line) > 48 or "附注" in line:
            continue
        for statement_name in _STATEMENT_NAMES:
            normalized = _normalize_text(statement_name)
            if normalized not in line:
                continue
            if statement_name == "资产负债表" and f"{normalized}日" in line:
                continue
            headings.add(statement_name)
    return headings


def _route_evidence_chunks(
    chunks: list[dict[str, Any]],
    targets: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """扫描全部分块，但只把可能含目标财务事实的分块发送给模型。"""
    targets_by_sheet: dict[str, list[dict[str, str]]] = {}
    for target in targets:
        targets_by_sheet.setdefault(str(target.get("sheet_name") or ""), []).append(
            target
        )

    inventory_by_source: dict[str, dict[str, Any]] = {}
    routed: list[dict[str, Any]] = []
    for chunk in chunks:
        source_ref = str(chunk.get("source_ref") or "")
        inventory = inventory_by_source.setdefault(
            source_ref,
            {
                "source_ref": source_ref,
                "source_name": str(chunk.get("source_name") or ""),
                "source_relative": str(chunk.get("source_relative") or ""),
                "total_chunks": 0,
                "candidate_chunks": 0,
                "total_chars": 0,
            },
        )
        inventory["total_chunks"] += 1
        inventory["total_chars"] += len(str(chunk.get("text") or ""))

        raw_text = str(chunk.get("text") or "")
        text = _normalize_text(raw_text)
        heading_names = _statement_headings(raw_text)
        heading_sheets = {
            sheet_name
            for sheet_name in targets_by_sheet
            if _normalize_statement(sheet_name) in _STATEMENT_NAMES
            and _normalize_statement(sheet_name) in heading_names
        }
        exact_targets: list[dict[str, str]] = []
        for target in targets:
            if any(variant in text for variant in _label_variants(target.get("label") or "")):
                exact_targets.append(target)

        if not heading_sheets and not exact_targets:
            continue

        candidates: dict[str, dict[str, str]] = {}
        for sheet_name in heading_sheets:
            for target in targets_by_sheet.get(sheet_name) or []:
                candidates[str(target.get("item_id") or "")] = target
        for target in exact_targets:
            candidates[str(target.get("item_id") or "")] = target

        routed_chunk = dict(chunk)
        routed_chunk["targets"] = list(candidates.values())
        routed_chunk["statement_hints"] = sorted(
            {
                _normalize_statement(sheet_name)
                for sheet_name in heading_sheets
                if sheet_name
            }
            | {
                _normalize_statement(target.get("sheet_name"))
                for target in exact_targets
                if target.get("sheet_name")
            }
        )
        routed.append(routed_chunk)
        inventory["candidate_chunks"] += 1

    return routed, list(inventory_by_source.values())


def _missing_ocr_sources(
    extract_root: Path,
    inventory: list[dict[str, Any]],
) -> list[str]:
    source_dir = extract_root / "sources"
    if not source_dir.is_dir():
        return []
    processed_names = {
        str(item.get("source_relative") or item.get("source_name") or "")
        for item in inventory
        if item.get("source_name")
    }
    return sorted(
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and path.name not in processed_names
    )


def prepare_evidence_chunks_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    chunks = build_case2_ocr_chunks(root)
    if not chunks:
        raise RuntimeError("Case2 未找到可用 OCR 文本，无法建立全局证据目录")
    targets = _target_items(state.get("fill_schema") or {})
    if not targets:
        raise RuntimeError("Case2 fill schema 中没有待填指标")
    routed_chunks, source_inventory = _route_evidence_chunks(chunks, targets)
    missing_sources = _missing_ocr_sources(root, source_inventory)
    if missing_sources:
        preview = "、".join(missing_sources[:5])
        suffix = " 等" if len(missing_sources) > 5 else ""
        raise RuntimeError(
            f"Case2 有 {len(missing_sources)} 个源文件没有可用 OCR 文本："
            f"{preview}{suffix}"
        )
    if not routed_chunks:
        raise RuntimeError(
            "Case2 已扫描全部 OCR 文本，"
            "但没有找到与当前模板科目匹配的财务报表分块"
        )
    total_chars = sum(len(str(chunk.get("text") or "")) for chunk in chunks)
    return {
        "material_chunks": routed_chunks,
        "evidence_targets": targets,
        "source_inventory": source_inventory,
        "log_lines": [
            f"OCR 全量扫描={len(chunks)} 分块/{len(source_inventory)} 文件，"
            f"总字符={total_chars}；财务候选分块={len(routed_chunks)}"
        ],
        "progress": (
            f"已扫描全部 {len(chunks)} 个 OCR 分块，"
            f"准备读取 {len(routed_chunks)} 个财务候选分块"
        ),
    }


def extract_evidence_chunk_node(state: dict[str, Any]) -> dict[str, Any]:
    chunk = state.get("material_chunk") or {}
    targets = state.get("evidence_targets") or []
    source_ref = str(chunk.get("source_ref") or "")
    source_location = (
        f"{source_ref}#page={chunk['page']}" if chunk.get("page") else source_ref
    )
    llm = structured_llm(Case2ChunkEvidence, method="json_mode")
    result: Case2ChunkEvidence = llm.invoke(
        [
            ("system", prompts.EXTRACT_EVIDENCE_SYSTEM),
            (
                "human",
                prompts.EXTRACT_EVIDENCE_USER.format(
                    task_id=state.get("task_id") or "",
                    chunk_index=int(state.get("chunk_index") or 0) + 1,
                    total_chunks=int(state.get("total_chunks") or 0),
                    source_ref=source_location,
                    targets_json=json.dumps(targets, ensure_ascii=False),
                    chunk_text=chunk.get("text") or "",
                ),
            ),
        ],
        # 不设输出上限：一页密集的资产负债表证据本来就可能写满几千 token，
        # 硬上限会把正常输出截断（任务 5c17dcad 即此）。空转由退化探测负责中止；
        # 非流式时探测器无效，退回一个宽松上限兜底。
        config=guard_config(),
        **fallback_max_tokens(_EVIDENCE_FALLBACK_MAX_TOKENS),
    )

    period_defaults: dict[str, Any] = {}
    if result.period_hints:
        period_defaults = result.period_hints[0].model_dump()

    target_by_id = {
        str(target.get("item_id") or ""): target
        for target in targets
        if target.get("item_id")
    }
    allowed_ids = set(target_by_id)
    facts: list[dict[str, Any]] = []
    discarded = 0
    for fact in result.facts:
        data = fact.model_dump()
        for key in (
            "entity_name",
            "statement_scope",
            "statement_name",
            "source_period",
            "report_date",
        ):
            if not data.get(key) and period_defaults.get(key):
                data[key] = period_defaults[key]
        if data.get("item_id") not in allowed_ids:
            discarded += 1
            continue
        value = data.get("value")
        if value is None or (
            isinstance(value, str) and value.strip().lower() in _NULL_TEXT
        ):
            continue
        data["source_ref"] = source_ref
        data["source_page"] = chunk.get("page")
        if not data.get("statement_name"):
            data["statement_name"] = target_by_id[data["item_id"]].get(
                "statement_name"
            )
        data["evidence_text"] = str(data.get("evidence_text") or "")[:400]
        facts.append(data)

    hints: list[dict[str, Any]] = []
    for hint in result.period_hints:
        data = hint.model_dump()
        if not str(data.get("evidence_text") or "").strip():
            continue
        data["source_ref"] = source_ref
        data["source_page"] = chunk.get("page")
        statement_hints = chunk.get("statement_hints") or []
        if not data.get("statement_name") and len(statement_hints) == 1:
            data["statement_name"] = statement_hints[0]
        data["evidence_text"] = str(data.get("evidence_text") or "")[:400]
        hints.append(data)

    index = int(state.get("chunk_index") or 0)
    total = int(state.get("total_chunks") or 0)
    return {
        "chunk_evidence": [
            {
                "source_ref": source_ref,
                "page": chunk.get("page"),
                "part_index": chunk.get("part_index"),
                "part_count": chunk.get("part_count"),
                "facts": facts,
                "period_hints": hints,
            }
        ],
        "log_lines": [
            f"证据分块 {index + 1}/{total}：facts={len(facts)}"
            + (f"，丢弃未知 item={discarded}" if discarded else "")
        ],
        "progress": f"正在读取 OCR 分块 {index + 1}/{total}",
    }


def _fact_key(fact: dict[str, Any]) -> tuple[str, ...]:
    value = str(fact.get("value") or "").replace(",", "").strip()
    return (
        str(fact.get("item_id") or ""),
        _normalize_text(fact.get("entity_name")),
        _normalize_scope(fact.get("statement_scope")),
        str(fact.get("statement_name") or "").strip(),
        str(fact.get("source_period") or "").strip(),
        str(fact.get("report_date") or "").strip(),
        value,
        str(fact.get("source_ref") or ""),
        str(fact.get("source_page") or ""),
    )


def _hint_key(hint: dict[str, Any]) -> tuple[str, ...]:
    return (
        _normalize_text(hint.get("entity_name")),
        _normalize_scope(hint.get("statement_scope")),
        str(hint.get("statement_name") or "").strip(),
        str(hint.get("report_date") or "").strip(),
        str(hint.get("source_period") or "").strip(),
        str(hint.get("source_ref") or ""),
        str(hint.get("source_page") or ""),
    )


def merge_evidence_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    facts_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    hints_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for chunk in state.get("chunk_evidence") or []:
        entries = list(chunk.get("facts") or []) + list(
            chunk.get("period_hints") or []
        )
        canonical_entity = _canonical_entity_name(
            [entry.get("entity_name") for entry in entries]
        )
        if canonical_entity:
            for entry in entries:
                if entry.get("entity_name"):
                    entry["entity_name"] = canonical_entity
        for fact in chunk.get("facts") or []:
            facts_by_key.setdefault(_fact_key(fact), fact)
        for hint in chunk.get("period_hints") or []:
            hints_by_key.setdefault(_hint_key(hint), hint)
    catalog = {
        "candidate_chunk_count": len(state.get("material_chunks") or []),
        "source_inventory": state.get("source_inventory") or [],
        "facts": list(facts_by_key.values()),
        "period_hints": list(hints_by_key.values()),
    }
    write_json(root / "outputs" / "case2_evidence_catalog.json", catalog)
    return {
        "evidence_catalog": catalog,
        "log_lines": [
            f"证据目录合并完成：facts={len(catalog['facts'])}，"
            f"period_hints={len(catalog['period_hints'])}"
        ],
        "progress": "已合并全量 OCR 证据",
    }


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _all_period_evidence(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return list(catalog.get("period_hints") or []) + list(catalog.get("facts") or [])


def _matching_period_evidence(
    entries: list[dict[str, Any]],
    column: dict[str, Any],
) -> list[dict[str, Any]]:
    report_date = _parse_date(column.get("report_date"))
    if report_date is None:
        return []
    expected_statement = _normalize_statement(column.get("statement_name"))
    # 比对交给 _entity_names_compatible，这里保留原始写法，别提前把括号批注抹掉
    expected_entity_raw = str(column.get("entity_name") or "")
    expected_entity = _normalize_text(expected_entity_raw)
    expected_scope = _normalize_scope(column.get("statement_scope"))
    expected_ref = str(column.get("source_ref") or "")

    matched: list[dict[str, Any]] = []
    for entry in entries:
        if _parse_date(entry.get("report_date")) != report_date:
            continue
        statement = _normalize_statement(entry.get("statement_name"))
        if expected_statement and statement and statement != expected_statement:
            continue
        entity = _normalize_text(entry.get("entity_name"))
        if expected_entity and entity and not _entity_names_compatible(
            expected_entity_raw, entry.get("entity_name")
        ):
            continue
        scope = _normalize_scope(entry.get("statement_scope"))
        if expected_scope and scope and scope != expected_scope:
            continue
        source_ref = str(entry.get("source_ref") or "")
        if expected_ref and source_ref != expected_ref:
            continue
        matched.append(entry)
    return matched


def _enrich_validated_column(
    column: dict[str, Any],
    *,
    sheet_name: str,
    entries: list[dict[str, Any]],
    preferred_entity: Any = "",
) -> dict[str, Any]:
    data = dict(column)
    data["statement_name"] = (
        _normalize_statement(data.get("statement_name"))
        or _normalize_statement(sheet_name)
    )
    matched = _matching_period_evidence(entries, data)
    if not matched:
        data["report_date"] = None
        data["source_ref"] = None
        data["confidence"] = "low"
        return data

    refs = sorted(
        {str(entry.get("source_ref") or "") for entry in matched if entry.get("source_ref")}
    )
    entities = sorted(
        {
            str(entry.get("entity_name") or "").strip()
            for entry in matched
            if entry.get("entity_name")
        }
    )
    canonical_entity = _canonical_entity_name(entities, preferred=preferred_entity)
    scopes = sorted(
        {
            _normalize_scope(entry.get("statement_scope"))
            for entry in matched
            if _normalize_scope(entry.get("statement_scope"))
        }
    )
    if not data.get("source_ref") and len(refs) == 1:
        data["source_ref"] = refs[0]
    if canonical_entity:
        data["entity_name"] = canonical_entity
    if not _normalize_scope(data.get("statement_scope")) and len(scopes) == 1:
        data["statement_scope"] = scopes[0]
    if not data.get("evidence_text"):
        data["evidence_text"] = str(matched[0].get("evidence_text") or "")[:400]
    return data


def _fact_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").replace("，", "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _carryforward_review_flags(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """时点表勾稽体检：本期年初数应等于上期期末数。只提示，不改数。"""
    buckets: dict[tuple[date, str], dict[str, float]] = {}
    for fact in catalog.get("facts") or []:
        if _normalize_statement(fact.get("statement_name")) != "资产负债表":
            continue
        report_date = _parse_date(fact.get("report_date"))
        if report_date is None:
            continue
        period_text = str(fact.get("source_period") or "")
        if _OPENING_PERIOD_RE.search(period_text):
            kind = "opening"
        elif _CLOSING_PERIOD_RE.search(period_text):
            kind = "closing"
        else:
            continue
        number = _fact_number(fact.get("value"))
        subject = _normalize_text(fact.get("subject_name"))
        if number is None or not subject:
            continue
        buckets.setdefault((report_date, kind), {}).setdefault(subject, number)

    flags: list[dict[str, Any]] = []
    for (report_date, kind), opening in sorted(buckets.items(), key=lambda x: str(x[0])):
        if kind != "opening":
            continue
        try:
            previous = date(report_date.year - 1, 12, 31)
        except ValueError:
            continue
        closing = buckets.get((previous, "closing"))
        if not closing:
            continue
        common = sorted(set(opening) & set(closing))
        if len(common) < 3:
            continue
        mismatch = [
            subject
            for subject in common
            if abs(opening[subject] - closing[subject])
            > max(1.0, abs(closing[subject]) * 0.005)
        ]
        if len(mismatch) * 2 <= len(common):
            continue
        flags.append(
            {
                "kind": "carryforward_mismatch",
                "statement": "资产负债表",
                "report_date": report_date.isoformat(),
                "compared_with": previous.isoformat(),
                "matched_subjects": len(common),
                "mismatched_subjects": len(mismatch),
                "detail": (
                    f"{report_date.isoformat()} 的年初数与 {previous.isoformat()} 的期末数"
                    f"有 {len(mismatch)}/{len(common)} 个科目对不上，"
                    "该页期末/年初两列可能被识别颠倒，请人工复核后再采用该期数据"
                ),
            }
        )
    return flags


def _validate_sheet_identity(
    columns: list[dict[str, Any]], *, preferred_entity: Any = ""
) -> None:
    by_sheet: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        by_sheet.setdefault(str(column.get("sheet_name") or ""), []).append(column)
    for sheet_name, sheet_columns in by_sheet.items():
        entity_names = {
            str(column.get("entity_name") or "").strip()
            for column in sheet_columns
            if _normalize_text(column.get("entity_name"))
        }
        canonical_entity = _canonical_entity_name(
            list(entity_names), preferred=preferred_entity
        )
        if canonical_entity:
            for column in sheet_columns:
                if column.get("entity_name"):
                    column["entity_name"] = canonical_entity
        entities = {_normalize_text(name) for name in entity_names}
        scopes = {
            _normalize_scope(column.get("statement_scope"))
            for column in sheet_columns
            if _normalize_scope(column.get("statement_scope"))
        }
        if len(entities) > 1 and not canonical_entity:
            raise RuntimeError(f"Case2 {sheet_name} 期次映射混入多个企业主体")
        if len(scopes) > 1:
            raise RuntimeError(f"Case2 {sheet_name} 期次映射混入多个报表口径")


def build_period_map_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    schema = state.get("fill_schema") or {}
    catalog = state.get("evidence_catalog") or {}
    sheets: list[dict[str, Any]] = []
    allowed: dict[tuple[str, str], str] = {}
    for sheet in schema.get("sheets") or []:
        sheet_name = str(sheet.get("sheet") or sheet.get("name") or "")
        headers = sheet.get("column_headers") or {}
        if not headers or not (sheet.get("items") or []):
            continue
        sheets.append({"sheet_name": sheet_name, "column_headers": headers})
        for key, label in headers.items():
            allowed[(sheet_name, str(key))] = str(label or "")

    fact_periods: dict[tuple[str, ...], dict[str, Any]] = {}
    for fact in catalog.get("facts") or []:
        compact = {
            "entity_name": fact.get("entity_name"),
            "statement_scope": fact.get("statement_scope"),
            "statement_name": fact.get("statement_name"),
            "source_period": fact.get("source_period"),
            "report_date": fact.get("report_date"),
            "source_ref": fact.get("source_ref"),
            "source_page": fact.get("source_page"),
            "evidence_text": fact.get("evidence_text"),
        }
        key = tuple(str(compact.get(name) or "") for name in compact)
        fact_periods.setdefault(key, compact)
    period_evidence = {
        "source_inventory": catalog.get("source_inventory") or [],
        "period_hints": catalog.get("period_hints") or [],
        "fact_periods": list(fact_periods.values()),
    }
    llm = structured_llm(Case2PeriodMap, method="json_mode")
    result: Case2PeriodMap = llm.invoke(
        [
            ("system", prompts.MAP_PERIODS_SYSTEM),
            (
                "human",
                prompts.MAP_PERIODS_USER.format(
                    task_id=state.get("task_id") or "",
                    sheets_json=json.dumps(sheets, ensure_ascii=False, indent=2),
                    user_rules=(state.get("user_rules") or "（无）")[:4000],
                    period_evidence_json=json.dumps(
                        period_evidence, ensure_ascii=False
                    ),
                ),
            ),
        ],
        max_tokens=_PERIOD_MAP_MAX_TOKENS,
        config=guard_config(),
    )

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    allowed_refs = {
        str(entry.get("source_ref") or "")
        for entry in list(catalog.get("period_hints") or [])
        + list(catalog.get("facts") or [])
        if entry.get("source_ref")
    }
    period_entries = _all_period_evidence(catalog)
    dominant_entity = _dominant_entity_name(catalog)
    for column in result.columns:
        data = column.model_dump()
        if not data.get("sheet_name"):
            matching_keys = [
                key for key in allowed if key[1] == data.get("field_key")
            ]
            if len(matching_keys) == 1:
                data["sheet_name"] = matching_keys[0][0]
        key = (data.get("sheet_name") or "", data.get("field_key") or "")
        if key in allowed and key not in by_key:
            data["column_label"] = allowed[key]
            if data.get("source_ref") not in allowed_refs:
                data["source_ref"] = None
            by_key[key] = _enrich_validated_column(
                data,
                sheet_name=key[0],
                entries=period_entries,
                preferred_entity=dominant_entity,
            )

    for key, label in allowed.items():
        by_key.setdefault(
            key,
            {
                "sheet_name": key[0],
                "field_key": key[1],
                "column_label": label,
                "entity_name": None,
                "statement_scope": "未知",
                "source_period": None,
                "report_date": None,
                "statement_name": _normalize_statement(key[0]),
                "confidence": "low",
                "evidence_text": None,
                "source_ref": None,
            },
        )

    period_map = {"columns": list(by_key.values())}
    _validate_sheet_identity(period_map["columns"], preferred_entity=dominant_entity)
    mapped = sum(1 for column in period_map["columns"] if column.get("report_date"))
    if not mapped:
        raise RuntimeError("Case2 未能从材料证据建立任何报告期映射")

    review_flags: list[dict[str, Any]] = []
    for column in period_map["columns"]:
        if column.get("report_date"):
            continue
        review_flags.append(
            {
                "kind": "period_unmapped",
                "sheet_name": column.get("sheet_name"),
                "field_key": column.get("field_key"),
                "column_label": column.get("column_label"),
                "detail": (
                    f"{column.get('field_key')} 列（{column.get('column_label')}）"
                    "未能在证据中确定报告期，该列不会参与填报；"
                    "留空原因是期次未映射，不代表源文件中没有这期数据"
                ),
            }
        )
    variants = _entity_variants(catalog)
    if len(variants) > 1:
        merged = _fuzzy_entity_pairs(catalog)
        detail = "证据中出现多个公司名称写法：" + "、".join(variants)
        if merged:
            detail += "；其中 " + "、".join(
                f"「{left}」与「{right}」" for left, right in merged
            ) + " 已按同一主体的 OCR 变体处理，请确认确为同一家公司"
        review_flags.append({"kind": "entity_variants", "detail": detail})
    review_flags.extend(_carryforward_review_flags(catalog))
    period_map["review_flags"] = review_flags
    add_review_flags(root, review_flags, stage="map_periods")

    write_json(root / "outputs" / "case2_period_map.json", period_map)
    log_lines = [f"全局期次映射完成：{mapped}/{len(period_map['columns'])} 列"]
    if review_flags:
        log_lines.append(f"期次阶段复核提示={len(review_flags)} 条")
    return {
        "period_mapping": period_map,
        "log_lines": log_lines,
        "progress": "已建立全局报告期映射",
    }


def facts_for_item_ids(
    catalog: dict[str, Any], item_ids: set[str]
) -> list[dict[str, Any]]:
    return [
        fact
        for fact in catalog.get("facts") or []
        if str(fact.get("item_id") or "") in item_ids
    ]


def facts_for_fill(
    catalog: dict[str, Any],
    item_ids: set[str],
    *,
    sheet_name: str,
    period_mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    """按当前 sheet 的主体、口径和报告期过滤事实，避免跨材料混用。"""
    columns = [
        column
        for column in period_mapping.get("columns") or []
        if str(column.get("sheet_name") or "") == sheet_name
    ]
    entities = {
        str(column.get("entity_name") or "").strip()
        for column in columns
        if _normalize_text(column.get("entity_name"))
    }
    scopes = {
        _normalize_scope(column.get("statement_scope"))
        for column in columns
        if _normalize_scope(column.get("statement_scope"))
    }
    report_dates = {
        parsed
        for column in columns
        if (parsed := _parse_date(column.get("report_date"))) is not None
    }
    source_refs = {
        str(column.get("source_ref") or "")
        for column in columns
        if column.get("source_ref")
    }
    statement_name = _normalize_statement(sheet_name)

    filtered: list[dict[str, Any]] = []
    for fact in facts_for_item_ids(catalog, item_ids):
        fact_statement = _normalize_statement(fact.get("statement_name"))
        if fact_statement and statement_name and fact_statement != statement_name:
            continue
        fact_entity = str(fact.get("entity_name") or "").strip()
        fact_scope = _normalize_scope(fact.get("statement_scope"))
        fact_ref = str(fact.get("source_ref") or "")
        if entities and fact_entity and not any(
            _entity_names_compatible(fact_entity, entity)
            for entity in entities
        ):
            continue
        if scopes and fact_scope and fact_scope not in scopes:
            continue
        if entities and not fact_entity and source_refs and fact_ref not in source_refs:
            continue
        if scopes and not fact_scope and source_refs and fact_ref not in source_refs:
            continue
        fact_date_text = str(fact.get("report_date") or "")
        fact_date = _parse_date(fact_date_text)
        if report_dates and fact_date_text and fact_date not in report_dates:
            continue
        filtered.append(fact)
    return filtered

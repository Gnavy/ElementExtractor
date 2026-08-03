from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from app.agents.llm import guard_config, output_cap, structured_llm
from app.agents.prompts import case2 as prompts
from app.agents.schemas.case2_item import Case2ChunkEvidence, Case2PeriodMap
from app.agents.tools.context import write_json
from app.services.case2_amounts import parse_amount
from app.services.case2_defaults import MAX_FILL_LOGIC_RULES_LEN
from app.services.case2_review import add_review_flags


_CHUNK_CHARS = 7000
_CHUNK_OVERLAP = 800
# 证据抽取的输出上限。实测最大的一块（121 个指标、25025 字 prompt）正常输出
# 10080 token，这里留约 3 倍余量：正常请求碰不到，退化时能兜住。
_EVIDENCE_MAX_TOKENS = 32768
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

    fuzzy 仅认长名字、长度差 ≤1 且编辑距离 ≤1 的 OCR 错字变体；
    母子公司、短名差一字均判为不同主体。
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


_SUBJECT_PAREN_RE = re.compile(r"[（(][^)）]*[)）]")


def _subject_keys(subject: Any) -> set[str]:
    """模板标签与源文档写法常有出入：括号后缀、「其中/加/减」前缀都要能对上。

    分块路由与事实落地校验都要用它，必须是同一份定义。2026-07-31 任务 a9bb0249：
    路由侧漏了「去括号后缀」这一种，模板标签「实收资本(或股本)」对不上源文档的
    「实收资本」，该指标没被派给含它的分块，2021 那一期整个漏抽。
    """
    text = str(subject or "")
    keys = {
        _normalize_text(text),
        _normalize_text(_SUBJECT_PAREN_RE.sub("", text)),
        _normalize_text(_LABEL_PREFIX_RE.sub("", text)),
    }
    return {key for key in keys if len(key) >= 2}


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
            if any(key in text for key in _subject_keys(target.get("label") or "")):
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
        # 空转由退化探测尽早中止；上限是兜底的确定性终止条件，流式也必须设
        config=guard_config(),
        **output_cap(_EVIDENCE_MAX_TOKENS),
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


_LINE_NUMBER_RE = re.compile(r"-?[\d][\d,.\s`^、]*\d|\d")


_STATEMENT_NAME_RE = re.compile(r"资产负债表|利润表|现金流量表|所有者权益变动表")
# 附注、明细、构成项的标题不算主表区——把它们认成主表，落地校验就挡不住抄错地方
_NOTES_HEAD_RE = re.compile(r"附注|明细|构成|续表|附表")
# 报表标题与表格之间常夹「## 2023年12月31日」「## 单位：元」这类行，不算区间结束
_BENIGN_HEAD_RE = re.compile(r"^#+\s*(20\d{2}[年\-/].*|单位[:：].*|编制单位.*)$")


def _is_statement_head(stripped: str) -> bool:
    """标题行是否为三大报表的主表标题。

    只要求「含报表名」而非「等于报表名」：扫描件的水印、骑缝章文字常被 OCR 并进
    标题行（东厦 2021 页读成「## 仅限用于渐商资产东清(-d2o地块能资内准 利润表」），
    按等值匹配会让整张表落在主表区之外，该页事实全部判成无据。
    """
    if not stripped.startswith("#"):
        return False
    if _NOTES_HEAD_RE.search(stripped):
        return False
    return bool(_STATEMENT_NAME_RE.search(stripped))


def _source_line_index(
    root: Path, source_ref: str
) -> list[tuple[str, set[float], bool, int]]:
    """源文档每一行 →（归一化文本, 该行所有数值, 是否属于主表区, 所属报表编号）。

    主表区＝从三大报表标题起、到下一个非报表标题止。附注明细表里也会出现
    「递延所得税资产 | 18,763,198.09」这样的行，只按「同行出现」判定会把它
    当成主表科目的依据——2026-07-31 任务 dcb2e2bd 的 C129/D129 即由此而来。

    报表编号按标题逐张递增（非主表区为 -1）：一份材料常含多张同类报表（东厦四个
    报告期各一张），错行检测必须按单张统计，否则对齐的表会把错行的表投票压过去。
    """
    path = root / str(source_ref or "").split("#")[0]
    if not path.is_file():
        return []
    rows: list[tuple[str, set[float], bool, int]] = []
    inside_main = False
    block_id = -1
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if _is_statement_head(stripped):
            inside_main = True
            block_id += 1
        elif stripped.startswith("#") and not _BENIGN_HEAD_RE.match(stripped):
            inside_main = False
        numbers: set[float] = set()
        for match in _LINE_NUMBER_RE.finditer(line):
            value = parse_amount(match.group(0))
            if value is not None:
                numbers.add(round(value, 2))
        rows.append(
            (_normalize_text(line), numbers, inside_main, block_id if inside_main else -1)
        )
    return rows


def _fact_is_grounded(
    fact: dict[str, Any],
    rows: list[tuple[str, set[float], bool, int]],
    *,
    row_offsets: list[int] | None = None,
) -> bool:
    """事实要能在源文档里落地：科目名与数值同行，且该行位于主表区。

    两类错误都要拦：
    1. 编造——模型把主表某空行的科目名与相邻行的数值配在一起，再写出一条原文里
       并不存在的 evidence_text（任务 dcb2e2bd 的「递延所得税资产 18,763,198.09」）。
    2. 抄错地方——附注明细表里确实有「递延所得税资产 | 18,763,198.09」这一行，
       但那是「其他非流动资产」的构成项，不是主表科目。

    主表区里根本没有该科目时，允许用附注等其他位置的依据兜底：有些科目主表不列示，
    只在附注披露，一律拒绝会误伤。

    ``row_offsets`` 是与 rows 等长的逐行偏移表，用于表格科目名与数值整体错行的
    情形，由 ``_detect_row_offsets()`` 按单张报表统计定出，不由单条事实自行选择。
    """
    value = fact.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True  # 非数值事实不在本检查范围
    if not rows:
        return True  # 源文档取不到就不做判断，不冤枉
    keys = _subject_keys(fact.get("subject_name"))
    if not keys:
        return True
    target = round(float(value), 2)

    def _numbers_at(index: int) -> set[float]:
        shifted = index + (row_offsets[index] if row_offsets else 0)
        return rows[shifted][1] if 0 <= shifted < len(rows) else set()

    subject_in_main = False
    for index, row in enumerate(rows):
        text, _numbers, in_main = row[0], row[1], row[2]
        if not any(key in text for key in keys):
            continue
        if in_main:
            subject_in_main = True
            if target in _numbers_at(index):
                return True

    if subject_in_main:
        # 主表列示了该科目（哪怕为空），就不接受主表之外的数值
        return False
    # 主表没有该科目，退而接受其他位置的同行依据
    return any(
        target in _numbers_at(index) and any(key in row[0] for key in keys)
        for index, row in enumerate(rows)
    )


# 判定错行所需的最少命中事实数，低于此数不足以排除偶然
_ROW_OFFSET_MIN_HITS = 5
# 错行偏移的候选范围，只考虑表格整体下移
_ROW_OFFSET_CANDIDATES = (1, 2)


def _main_blocks(rows: list[tuple[str, set[float], bool, int]]) -> list[tuple[int, int]]:
    """按报表编号切出的主表区行段，每段对应一张报表。"""
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    current = -1
    for index, row in enumerate(rows):
        block_id = row[3] if len(row) > 3 else (0 if row[2] else -1)
        if block_id != current:
            if start is not None:
                blocks.append((start, index))
            start = index if block_id >= 0 else None
            current = block_id
    if start is not None:
        blocks.append((start, len(rows)))
    return blocks


def _block_hits(
    facts: list[dict[str, Any]],
    rows: list[tuple[str, set[float], bool, int]],
    block: tuple[int, int],
    offset: int,
) -> int:
    """该段内「科目名所在行 + offset 行含目标数值」的事实条数。"""
    start, end = block
    hits = 0
    for fact in facts:
        value = fact.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        keys = _subject_keys(fact.get("subject_name"))
        if not keys:
            continue
        target = round(float(value), 2)
        for index in range(start, end):
            if not any(key in rows[index][0] for key in keys):
                continue
            shifted = index + offset
            if 0 <= shifted < len(rows) and target in rows[shifted][1]:
                hits += 1
                break
    return hits


def _detect_row_offsets(
    facts: list[dict[str, Any]], rows: list[tuple[str, set[float], bool, int]]
) -> list[int]:
    """逐张报表定错行偏移，返回与 rows 等长的逐行偏移表。

    扫描件的表头被并进首个科目行时，其后每一行的科目名都比数值晚一行，按「同行」
    逐条判会把整张表的事实全部误杀。**必须按单张报表统计**：一份材料里常同时有
    对齐的表和错行的表（东厦四个报告期各一张，只有三张错行），按整个文件统计会
    被对齐的那张冲掉。

    单条事实错配（dcb2e2bd 那种编造）形不成整张表的规律，因此要求非零偏移的命中
    数严格多于零偏移，且达到最小条数。
    """
    offsets = [0] * len(rows)
    for block in _main_blocks(rows):
        base = _block_hits(facts, rows, block, 0)
        best_offset, best_hits = 0, base
        for offset in _ROW_OFFSET_CANDIDATES:
            hits = _block_hits(facts, rows, block, offset)
            if hits >= _ROW_OFFSET_MIN_HITS and hits > best_hits:
                best_offset, best_hits = offset, hits
        if best_offset:
            for index in range(*block):
                offsets[index] = best_offset
    return offsets


def _mark_grounding(
    root: Path, facts: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """标注每条事实是否有源文档依据；返回（无据事实清单, 各源文件检出的错行偏移）。"""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_source.setdefault(str(fact.get("source_ref") or ""), []).append(fact)

    ungrounded: list[dict[str, Any]] = []
    shifted: dict[str, list[int]] = {}
    for source_ref, source_facts in by_source.items():
        rows = _source_line_index(root, source_ref)
        row_offsets = _detect_row_offsets(source_facts, rows)
        found = sorted({offset for offset in row_offsets if offset})
        if found:
            shifted[source_ref] = found
        for fact in source_facts:
            if _fact_is_grounded(fact, rows, row_offsets=row_offsets):
                continue
            fact["grounded"] = False
            ungrounded.append(fact)
    return ungrounded, shifted


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
    facts = list(facts_by_key.values())
    ungrounded, row_offsets = _mark_grounding(root, facts)
    catalog = {
        "candidate_chunk_count": len(state.get("material_chunks") or []),
        "source_inventory": state.get("source_inventory") or [],
        "facts": facts,
        "period_hints": list(hints_by_key.values()),
        "source_row_offsets": row_offsets,
    }
    write_json(root / "outputs" / "case2_evidence_catalog.json", catalog)
    if row_offsets:
        add_review_flags(
            root,
            [
                {
                    "kind": "source_rows_shifted",
                    "detail": (
                        "以下源文件存在表格科目名与数值整体错行的报表，落地校验已按检出的"
                        "偏移核对，取数请重点抽查："
                        + "；".join(
                            f"{ref.rsplit('/', 1)[-1]} 偏移 {'/'.join(str(o) for o in found)} 行"
                            for ref, found in row_offsets.items()
                        )
                    ),
                }
            ],
            stage="merge_evidence",
        )
    if ungrounded:
        preview = "；".join(
            f"{f.get('subject_name')}={f.get('value')}" for f in ungrounded[:5]
        )
        add_review_flags(
            root,
            [
                {
                    "kind": "fact_not_grounded",
                    "detail": (
                        f"{len(ungrounded)} 条事实在源文档中找不到「科目名与数值同行」的依据，"
                        f"已排除在填报之外：{preview}"
                        + ("…" if len(ungrounded) > 5 else "")
                    ),
                }
            ],
            stage="merge_evidence",
        )
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
    expected_scope = _normalize_scope(column.get("statement_scope"))
    expected_ref = str(column.get("source_ref") or "")

    matched: list[dict[str, Any]] = []
    for entry in entries:
        if _parse_date(entry.get("report_date")) != report_date:
            continue
        statement = _normalize_statement(entry.get("statement_name"))
        if expected_statement and statement and statement != expected_statement:
            continue
        scope = _normalize_scope(entry.get("statement_scope"))
        if expected_scope and scope and scope != expected_scope:
            continue
        matched.append(entry)
    # 同一报告期的数据可能散落在多份材料里（本期数在当年报告、比较数在次年报告），
    # 来源文件只作排序偏好，不作过滤条件
    if expected_ref:
        matched.sort(key=lambda e: str(e.get("source_ref") or "") != expected_ref)
    return matched


def _recover_report_date(data: dict[str, Any]) -> bool:
    """列未给出报告期时，从证据文本里取回明确写出的日期。

    取回的日期仍须由事实匹配确认，匹配不上照旧作未映射处理。
    """
    if _parse_date(data.get("report_date")) is not None:
        return False
    for key in ("source_period", "evidence_text"):
        parsed = _parse_date(data.get(key))
        if parsed is not None:
            data["report_date"] = parsed.isoformat()
            return True
    return False


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
    recovered = _recover_report_date(data)
    matched = _matching_period_evidence(entries, data)
    if recovered and matched:
        data["date_from_evidence_text"] = True
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
    return parse_amount(value)


def _carryforward_review_flags(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """时点表勾稽体检：本期年初数应等于上期期末数。只提示，不改数。"""
    # 年初桶按「日期 + 来源文档」分，期末桶按日期汇总。
    # 同一个日期的年初桶会同时收到多份报告的事实，而各报告的 report_date 口径不同
    # （见下方注释），混在一起比谁都对不上一半——2026-07-31 任务 a9bb0249 即如此：
    # 「2022-12-31 年初」桶里，货币资金来自 2023 报告（实为 2022 年末），
    # 应付账款来自 2022 报告（实为 2021 年末）。
    openings: dict[tuple[date, str], dict[str, float]] = {}
    closings: dict[date, dict[str, float]] = {}
    closing_sources: dict[date, set[str]] = {}
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
        if kind == "opening":
            source = str(fact.get("source_ref") or "")
            openings.setdefault((report_date, source), {}).setdefault(subject, number)
        else:
            closings.setdefault(report_date, {}).setdefault(subject, number)
            closing_sources.setdefault(report_date, set()).add(
                str(fact.get("source_ref") or "")
            )

    flags: list[dict[str, Any]] = []
    seen_dates: set[date] = set()
    for (report_date, source), opening in sorted(
        openings.items(), key=lambda x: (str(x[0][0]), x[0][1])
    ):
        # 年初列的 report_date 口径不统一：模型有时标成「该列所属期」（应比同日期末），
        # 有时标成「报表日」（应比上年期末）。同一份 2023 报告里两种都出现过。
        # 因此两种配对都试，任一对得上就不报警——真正的期末/年初颠倒两边都对不上。
        # 只按其中一种比，会把正确数据判成「两列被识别颠倒」，反过来误导人工复核。
        candidates = [report_date]
        try:
            candidates.append(date(report_date.year - 1, 12, 31))
        except ValueError:
            pass

        best: tuple[float, list[str], list[str], date] | None = None
        for candidate in candidates:
            closing = closings.get(candidate)
            if not closing:
                continue
            # 同一份报告的年初列与期末列本就是两期，不能互比。正确的对手报告不存在时
            # （如材料只有三年、没有 2020 年报），宁可不比，也不要拿它凑数——
            # 2026-07-31 任务 08adc5c3 由此报出「2021 年初 vs 2021 期末 26/29 不一致」。
            others = closing_sources.get(candidate, set()) - {source}
            if not others:
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
            score = len(mismatch) / len(common)
            if best is None or score < best[0]:
                best = (score, common, mismatch, candidate)

        if best is None:
            continue
        _, common, mismatch, compared = best
        if len(mismatch) * 2 <= len(common):
            continue
        if report_date in seen_dates:
            continue  # 同一期次只提示一次，来源不同不重复刷屏
        seen_dates.add(report_date)
        flags.append(
            {
                "kind": "carryforward_mismatch",
                "statement": "资产负债表",
                "report_date": report_date.isoformat(),
                "compared_with": compared.isoformat(),
                "matched_subjects": len(common),
                "mismatched_subjects": len(mismatch),
                "detail": (
                    f"{report_date.isoformat()} 的年初数与 {compared.isoformat()} 的期末数"
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
        scopes = {
            _normalize_scope(column.get("statement_scope"))
            for column in sheet_columns
            if _normalize_scope(column.get("statement_scope"))
        }
        if len(scopes) > 1:
            raise RuntimeError(f"Case2 {sheet_name} 期次映射混入多个报表口径")


def _column_source_key(column: dict[str, Any]) -> tuple[str, str]:
    return (
        str(column.get("source_ref") or ""),
        _normalize_text(column.get("source_period")),
    )


def _drop_duplicate_period_columns(
    columns: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], str]], list[tuple[dict[str, Any], str]]]:
    """同一张表两列映射到同一报告期时，判断是合法共用还是真冲突。

    返回（真冲突已取消映射的列, 合法共用的列），第二项元素是占用该报告期的列。

    **同源同口径视为合法共用**：材料只有年报时，「最近一期」与「本期(年报)」
    允许同为最新年报（MAP_PERIODS_SYSTEM 规则 8）。
    **来源或口径不同才是冲突**：材料期数少于模板列数时，模型会把最老那列硬映射
    成已用过的报告期——如 E 取 2023 报告的上期金额、F 取 2022 报告的本期金额，
    两列指向同一期却各有来源，会抢同一批事实。

    冲突时按 field_key 顺序（C→F 即最近→最远）保留先出现的列，数据从老的一端用尽。
    """
    dropped: list[tuple[dict[str, Any], str]] = []
    shared: list[tuple[dict[str, Any], str]] = []
    taken: dict[tuple[str, str], tuple[str, tuple[str, str]]] = {}
    for column in sorted(columns, key=lambda c: str(c.get("field_key") or "")):
        report_date = str(column.get("report_date") or "")
        if not report_date:
            continue
        key = (str(column.get("sheet_name") or ""), report_date)
        field_key = str(column.get("field_key") or "")
        source = _column_source_key(column)
        owner = taken.get(key)
        if owner is None:
            taken[key] = (field_key, source)
            continue
        if owner[1] == source:
            shared.append((column, owner[0]))
            continue
        dropped.append((dict(column), owner[0]))
        column["report_date"] = None
        column["source_period"] = None
        column["confidence"] = "low"
        column["evidence_text"] = None
        column["source_ref"] = None
    return dropped, shared


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
                    user_rules=(state.get("user_rules") or "（无）")[:MAX_FILL_LOGIC_RULES_LEN],
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
    duplicated, shared_periods = _drop_duplicate_period_columns(period_map["columns"])
    mapped = sum(1 for column in period_map["columns"] if column.get("report_date"))
    if not mapped:
        raise RuntimeError("Case2 未能从材料证据建立任何报告期映射")

    review_flags: list[dict[str, Any]] = []
    for column, taken_by in shared_periods:
        review_flags.append(
            {
                "kind": "period_shared",
                "sheet_name": column.get("sheet_name"),
                "field_key": column.get("field_key"),
                "detail": (
                    f"{column.get('sheet_name')} 列 {column.get('field_key')}"
                    f"（{column.get('column_label')}）与列 {taken_by} 同为 "
                    f"{column.get('report_date')} 的同一份来源与口径，两列将填入相同数据，"
                    "请确认模板是否本就如此"
                ),
            }
        )
    for column, taken_by in duplicated:
        review_flags.append(
            {
                "kind": "period_duplicated",
                "sheet_name": column.get("sheet_name"),
                "field_key": column.get("field_key"),
                "detail": (
                    f"{column.get('sheet_name')} 列 {column.get('field_key')}"
                    f"（{column.get('column_label')}）被映射到 {column.get('report_date')}，"
                    f"但该报告期已由列 {taken_by} 占用；材料很可能不含该列所需期次，"
                    "已取消映射并留空，请人工确认"
                ),
            }
        )
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
    for column in period_map["columns"]:
        if not column.pop("date_from_evidence_text", False):
            continue
        review_flags.append(
            {
                "kind": "period_date_from_evidence_text",
                "sheet_name": column.get("sheet_name"),
                "field_key": column.get("field_key"),
                "detail": (
                    f"{column.get('field_key')} 列（{column.get('column_label')}）"
                    f"的报告期 {column.get('report_date')} 取自证据说明文本，"
                    "已由事实匹配确认，仍建议复核该列期次"
                ),
            }
        )
    variants = _entity_variants(catalog)
    if len(variants) > 1:
        counts: dict[str, int] = {}
        for fact in catalog.get("facts") or []:
            name = str(fact.get("entity_name") or "").strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
        listed = "、".join(
            f"{name}（{counts.get(name, 0)} 条）"
            for name in sorted(variants, key=lambda n: -counts.get(n, 0))
        )
        review_flags.append(
            {
                "kind": "entity_variants",
                "detail": (
                    f"证据中出现 {len(variants)} 种公司名称写法：{listed}；"
                    "已按同一任务同一主体处理，若材料中确实混入了其他公司请重新分开建任务"
                ),
            }
        )
    rules_len = len(str(state.get("user_rules") or ""))
    if rules_len > MAX_FILL_LOGIC_RULES_LEN:
        review_flags.append(
            {
                "kind": "user_rules_truncated",
                "detail": (
                    f"用户填表规则共 {rules_len} 字，超出注入上限 "
                    f"{MAX_FILL_LOGIC_RULES_LEN} 字，末尾 "
                    f"{rules_len - MAX_FILL_LOGIC_RULES_LEN} 字未进入模型提示词；"
                    "---CALC--- 计算规则仍由 Python 全量执行，不受影响"
                ),
            }
        )
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
    # 无据事实（科目名与数值在源文档中不同行）不进填报上下文
    catalog = {
        **catalog,
        "facts": [f for f in (catalog.get("facts") or []) if f.get("grounded") is not False],
    }
    columns = [
        column
        for column in period_mapping.get("columns") or []
        if str(column.get("sheet_name") or "") == sheet_name
    ]
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
    statement_name = _normalize_statement(sheet_name)

    filtered: list[dict[str, Any]] = []
    for fact in facts_for_item_ids(catalog, item_ids):
        fact_statement = _normalize_statement(fact.get("statement_name"))
        if fact_statement and statement_name and fact_statement != statement_name:
            continue
        fact_scope = _normalize_scope(fact.get("statement_scope"))
        if scopes and fact_scope and fact_scope not in scopes:
            continue
        fact_date_text = str(fact.get("report_date") or "")
        fact_date = _parse_date(fact_date_text)
        if report_dates and fact_date_text and fact_date not in report_dates:
            continue
        filtered.append(fact)
    return filtered

"""
Match Case2 filled values to OCR sidecar cells and compute min confidence.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from ocr_confidence_export import default_confidence_threshold

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９，．－",
    "0123456789,.-",
)


def normalize_value(text: Any) -> str:
    """Normalize text for fuzzy matching (whitespace, fullwidth, punctuation)."""
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_FULLWIDTH_TRANS)
    s = re.sub(r"[\s,，、]", "", s)
    s = re.sub(r"[年月日/\\.-]", "", s)
    return s.lower()


def extract_digit_run(text: Any) -> str:
    """Extract digits and decimal point for numeric comparison."""
    norm = normalize_value(text)
    m = re.search(r"-?\d+\.?\d*", norm)
    return m.group(0) if m else ""


def load_sidecar_index(extract_root: Path) -> dict[str, dict[str, Any]]:
    """
    Index sidecars by md_rel path (posix, relative to extract root).
    """
    index: dict[str, dict[str, Any]] = {}
    ocr_dir = extract_root / "ocr_text"
    if not ocr_dir.is_dir():
        return index

    for sidecar_path in ocr_dir.rglob("*.ocr_cells.json"):
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        md_rel = str(data.get("md_rel") or "").replace("\\", "/")
        if not md_rel:
            try:
                rel = sidecar_path.relative_to(extract_root)
                # foo.pdf.ocr_cells.json under ocr_text -> foo.pdf.md
                parts = rel.as_posix()
                if parts.endswith(".ocr_cells.json"):
                    md_rel = parts[: -len(".ocr_cells.json")] + ".md"
            except ValueError:
                continue
        index[md_rel] = data
    return index


def _cell_matches_value(cell_text: str, value: Any) -> bool:
    cell_norm = normalize_value(cell_text)
    val_norm = normalize_value(value)
    if not cell_norm or not val_norm:
        return False
    if cell_norm == val_norm:
        return True
    if val_norm in cell_norm or cell_norm in val_norm:
        return True
    cell_digits = extract_digit_run(cell_text)
    val_digits = extract_digit_run(value)
    if cell_digits and val_digits and cell_digits == val_digits:
        return True
    return False


def _ocr_md_refs(evidence_refs: list[Any]) -> list[str]:
    refs: list[str] = []
    for ref in evidence_refs or []:
        s = str(ref).replace("\\", "/").strip()
        if not s:
            continue
        if "ocr_text/" in s and s.endswith(".md"):
            refs.append(s)
    return refs


def match_ocr_confidence(
    value: Any,
    evidence_refs: list[Any],
    sidecar_index: dict[str, dict[str, Any]],
    *,
    threshold: float | None = None,
) -> tuple[float, list[str], str] | None:
    """
    Match filled value against OCR sidecar cells referenced in evidence_refs.

    Returns (min_confidence, matched_snippets, md_ref) or None if no OCR match.
    """
    if value is None or value == "":
        return None

    md_refs = _ocr_md_refs(evidence_refs)
    if not md_refs:
        return None

    best_min: float | None = None
    snippets: list[str] = []
    matched_md = ""

    for md_ref in md_refs:
        sidecar = sidecar_index.get(md_ref)
        if sidecar is None:
            continue

        for cell in sidecar.get("cells") or []:
            if not cell.get("from_ocr", True):
                continue
            text = cell.get("text") or ""
            if not _cell_matches_value(text, value):
                continue
            conf = float(cell.get("confidence") or 1.0)
            if best_min is None or conf < best_min:
                best_min = conf
                matched_md = md_ref
            snippet = text.strip()
            if snippet and snippet not in snippets:
                snippets.append(snippet[:80])

    if best_min is None:
        return None
    return best_min, snippets, matched_md


def is_low_ocr_confidence(
    value: Any,
    evidence_refs: list[Any],
    sidecar_index: dict[str, dict[str, Any]],
    *,
    threshold: float | None = None,
) -> tuple[bool, float | None, str]:
    """
    Returns (is_low, min_confidence, md_ref).
    """
    thresh = threshold if threshold is not None else default_confidence_threshold()
    result = match_ocr_confidence(
        value, evidence_refs, sidecar_index, threshold=thresh
    )
    if result is None:
        return False, None, ""
    min_conf, _snippets, md_ref = result
    return min_conf < thresh, min_conf, md_ref

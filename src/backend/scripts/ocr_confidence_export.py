"""
Export OCR per-cell confidence from Docling ConversionResult to JSON sidecar.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_confidence_threshold() -> float:
    raw = os.environ.get("OCR_CONFIDENCE_THRESHOLD", "0.7").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.7


def export_ocr_cells_sidecar(
    result: Any,
    sidecar_path: Path,
    *,
    source_rel: str,
    md_rel: str,
    confidence_threshold: float | None = None,
) -> int:
    """
    Write OCR cell confidence sidecar next to ocr_text markdown.
    Returns count of exported OCR cells.
    """
    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else default_confidence_threshold()
    )
    cells: list[dict[str, Any]] = []

    for page in result.pages:
        page_no = page.page_no
        page_size = page.size
        for cell in page.cells:
            if not cell.from_ocr:
                continue
            entry: dict[str, Any] = {
                "page": page_no,
                "text": cell.text or "",
                "confidence": float(cell.confidence),
                "from_ocr": True,
            }
            if page_size is not None and cell.rect is not None:
                try:
                    bb = (
                        cell.rect.to_bounding_box()
                        .to_top_left_origin(page_height=page_size.height)
                        .normalized(page_size=page_size)
                    )
                    entry["bbox"] = list(bb.as_tuple())
                except Exception:  # noqa: BLE001
                    pass
            cells.append(entry)

    payload = {
        "schema_version": 1,
        "source_rel": source_rel.replace("\\", "/"),
        "md_rel": md_rel.replace("\\", "/"),
        "confidence_threshold": threshold,
        "cells": cells,
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(cells)

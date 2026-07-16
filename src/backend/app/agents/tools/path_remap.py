"""Remap LLM-invented relative paths onto real extract filesystem paths."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def normalize_path_key(path: str) -> str:
    s = path.replace("\\", "/").strip().lstrip("/")
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=\d)", "", s)
    s = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[A-Za-z])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def build_path_index(extract_root: Path) -> dict[str, str]:
    """normalized_key -> actual relative posix path."""
    root = extract_root.resolve()
    index: dict[str, str] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if any(
            part in {".claude", "tools", "__MACOSX", "__pycache__"}
            for part in Path(rel).parts
        ):
            continue
        index[normalize_path_key(rel)] = rel
        # also index basename for weak fallback
        index.setdefault("bn:" + normalize_path_key(Path(rel).name), rel)
    return index


def remap_relative_path(path: str | None, index: dict[str, str]) -> str | None:
    if not path:
        return path
    raw = str(path).replace("\\", "/").strip()
    key = normalize_path_key(raw)
    if key in index:
        return index[key]
    bn = "bn:" + normalize_path_key(Path(raw).name)
    if bn in index:
        return index[bn]
    return raw


def remap_classification_payload(payload: dict[str, Any], extract_root: Path) -> dict[str, Any]:
    index = build_path_index(extract_root)
    for cat in payload.get("categories") or []:
        for f in cat.get("files") or []:
            if isinstance(f, dict) and f.get("relative_path"):
                f["relative_path"] = remap_relative_path(f["relative_path"], index)
    for u in payload.get("unclassified") or []:
        if isinstance(u, dict) and u.get("relative_path"):
            u["relative_path"] = remap_relative_path(u["relative_path"], index)
    return payload


def remap_extracted_payload(payload: dict[str, Any], extract_root: Path) -> dict[str, Any]:
    index = build_path_index(extract_root)
    fields = payload.get("fields") or {}
    for entry in fields.values():
        if not isinstance(entry, dict):
            continue
        sources = entry.get("source_files")
        if isinstance(sources, list):
            entry["source_files"] = [
                remap_relative_path(s, index) or s for s in sources if s
            ]
        evidence = entry.get("evidence")
        if isinstance(evidence, list):
            for ev in evidence:
                if isinstance(ev, dict) and ev.get("file"):
                    ev["file"] = remap_relative_path(ev["file"], index)
        val = entry.get("value")
        if isinstance(val, str) and (
            val.startswith("outputs/") or val.startswith("ocr_text/") or "/" in val
        ):
            remapped = remap_relative_path(val, index)
            if remapped:
                entry["value"] = remapped
        if isinstance(val, list):
            entry["value"] = [
                remap_relative_path(v, index) or v if isinstance(v, str) else v
                for v in val
            ]
    return payload

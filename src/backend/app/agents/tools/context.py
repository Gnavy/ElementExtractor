"""Material inventory and OCR snippet collection for RAG-lite prompts."""

from __future__ import annotations

import json
import re
from pathlib import Path


_SKIP_DIRS = {
    ".claude",
    "tools",
    "outputs",
    "inputs",
    "__MACOSX",
    ".git",
    "ocr_text",
}


def list_material_files(extract_root: Path, *, limit: int = 400) -> list[str]:
    """List relative material paths under extract_root (skip internals)."""
    root = extract_root.resolve()
    files: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if p.name.startswith("."):
            continue
        files.append(p.relative_to(root).as_posix())
        if len(files) >= limit:
            break
    return files


def _read_text_cap(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…(truncated)"


def expand_keywords(keywords: list[str] | None) -> list[str]:
    """
    Expand field names like「营业执照-文书名称」「注册资本_万元」into searchable tokens.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in keywords or []:
        if not raw or not str(raw).strip():
            continue
        text = str(raw).strip()
        parts = re.split(r"[-_／/\s,，、:;：；|]+", text)
        parts.append(text)
        # Also peel common prefixes like "营业执照-xxx"
        for part in parts:
            p = part.strip().lower()
            if len(p) < 2:
                continue
            # Drop pure units / noise
            if p in {"万元", "平方米", "元", "号", "名称", "摘要", "结论", "清单"}:
                continue
            if p not in seen:
                seen.add(p)
                out.append(p)
            # For long Chinese compounds, also keep first 2-4 chars chunks heuristic
            if re.search(r"[\u4e00-\u9fff]", p) and len(p) >= 4:
                for n in (2, 3, 4):
                    chunk = p[:n]
                    if chunk not in seen and chunk not in {"是否", "证明", "区域"}:
                        seen.add(chunk)
                        out.append(chunk)
    return out


def collect_ocr_snippets(
    extract_root: Path,
    *,
    keywords: list[str] | None = None,
    max_files: int = 12,
    max_chars_per_file: int = 3500,
    max_total_chars: int = 24000,
) -> str:
    """
    Collect OCR markdown (and optional indexes) as prompt context.

    Keywords only re-rank files; if no keyword hits, still return OCR content.
    Never return the empty placeholder when ocr_text/*.md exists.
    """
    ocr_dir = extract_root / "ocr_text"
    candidates: list[Path] = []
    if ocr_dir.is_dir():
        candidates.extend(sorted(ocr_dir.rglob("*.md")))

    for name in (
        "docx_comments_index.json",
        "ppt_text_index.json",
        "ocr_litigation_index.txt",
        "ocr_all_md_index.txt",
    ):
        p = extract_root / "outputs" / name
        if p.is_file():
            candidates.append(p)

    kws = expand_keywords(keywords)
    scored: list[tuple[int, Path]] = []
    for path in candidates:
        score = 1  # base score so every OCR file remains eligible
        low_name = path.as_posix().lower()
        head = ""
        if kws:
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:12000].lower()
            except OSError:
                head = ""
            for k in kws:
                if k in low_name:
                    score += 5
                if k and k in head:
                    score += 2
            # Prefer license / title-deed-ish paths for related field names
            boost_tokens = ("营业执照", "不动产权", "土地使用权", "规划许可", "施工许可", "预售")
            if any(t in "".join(kws) for t in boost_tokens):
                for t in boost_tokens:
                    if t in low_name:
                        score += 4
        scored.append((score, path))

    scored.sort(key=lambda x: (-x[0], str(x[1])))
    parts: list[str] = []
    total = 0
    for _, path in scored[:max_files]:
        try:
            rel = path.relative_to(extract_root).as_posix()
        except ValueError:
            rel = path.name
        body = _read_text_cap(path, max_chars_per_file)
        if not body.strip():
            continue
        chunk = f"### {rel}\n{body}\n"
        if total + len(chunk) > max_total_chars:
            remain = max_total_chars - total
            if remain > 200:
                parts.append(chunk[:remain] + "\n…(truncated)")
            break
        parts.append(chunk)
        total += len(chunk)

    if not parts:
        for rel in list_material_files(extract_root, limit=20):
            p = extract_root / rel
            if p.suffix.lower() in {".md", ".txt", ".json"}:
                parts.append(f"### {rel}\n{_read_text_cap(p, 1500)}\n")
                if len(parts) >= 5:
                    break

    if parts:
        return "\n".join(parts)
    file_list = "\n".join(f"- {p}" for p in list_material_files(extract_root, limit=40))
    return (
        "（未找到 OCR 文本。以下为文件清单，请仅依据文件名谨慎判断，无把握则 value=null。）\n"
        + (file_list or "（无文件）")
    )


def build_shared_material_context(
    extract_root: Path,
    *,
    max_total_chars: int = 30000,
) -> str:
    """Load a broad OCR corpus once for shared use across field extractions."""
    return collect_ocr_snippets(
        extract_root,
        keywords=None,
        max_files=16,
        max_chars_per_file=4000,
        max_total_chars=max_total_chars,
    )


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

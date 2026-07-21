#!/usr/bin/env python3
"""
提取 docx 正文（段落 + 表格）为可检索文本。

产出：
  - outputs/docx_text_index.json（结构化摘要）
  - ocr_text/<相对路径>.md（整篇，供 RAG）
  - ocr_text/<相对路径>.chunks/chunk_XXX.md（分块，提高关键词命中）

仅依赖标准库。用法（cwd = extract_root）：
  python tools/extract_docx_text.py --src . --out outputs/docx_text_index.json
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

CHUNK_CHARS = 2800
CHUNK_OVERLAP = 200


def _text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.findall(".//w:t", NS)).strip()


def _iter_blocks(doc: ET.Element) -> list[str]:
    """按文档顺序收集段落与表格行文本。"""
    body = doc.find("w:body", NS)
    if body is None:
        return []
    blocks: list[str] = []
    for child in list(body):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            t = _text(child)
            if t:
                blocks.append(t)
        elif tag == "tbl":
            for row in child.findall("./w:tr", NS):
                cells = []
                for cell in row.findall("./w:tc", NS):
                    ct = _text(cell)
                    if ct:
                        cells.append(ct)
                if cells:
                    blocks.append(" | ".join(cells))
    return blocks


def extract_docx_body(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return {
                "file": path.as_posix(),
                "paragraph_count": 0,
                "char_count": 0,
                "error": "缺少 word/document.xml",
            }
        doc = ET.fromstring(zf.read("word/document.xml"))
    blocks = _iter_blocks(doc)
    full = "\n".join(blocks)
    return {
        "file": path.as_posix(),
        "paragraph_count": len(blocks),
        "char_count": len(full),
        "text": full,
    }


def _write_chunks(md_path: Path, text: str) -> int:
    if not text.strip():
        return 0
    chunk_dir = md_path.with_suffix(md_path.suffix + ".chunks")
    # ocr_text/foo.docx.md -> ocr_text/foo.docx.md.chunks/
    chunk_dir.mkdir(parents=True, exist_ok=True)
    # clear old chunks
    for old in chunk_dir.glob("chunk_*.md"):
        old.unlink(missing_ok=True)

    n = 0
    i = 0
    length = len(text)
    while i < length:
        end = min(length, i + CHUNK_CHARS)
        # prefer break at newline
        if end < length:
            nl = text.rfind("\n", i + CHUNK_CHARS // 2, end)
            if nl > i:
                end = nl + 1
        piece = text[i:end].strip()
        if piece:
            n += 1
            (chunk_dir / f"chunk_{n:03d}.md").write_text(
                f"<!-- source={md_path.name} offset={i} -->\n{piece}\n",
                encoding="utf-8",
            )
        if end >= length:
            break
        i = max(end - CHUNK_OVERLAP, i + 1)
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="提取 docx 正文文本")
    p.add_argument("--src", required=True, help="docx 文件或目录")
    p.add_argument("--out", required=True, help="输出 json，如 outputs/docx_text_index.json")
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    if not str(src).startswith(str(cwd)) or not str(out).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录下")

    files = [src] if src.is_file() else sorted(src.rglob("*.docx"))
    docs = []
    ocr_root = cwd / "ocr_text"
    ocr_root.mkdir(parents=True, exist_ok=True)

    for f in files:
        if not f.is_file() or f.suffix.lower() != ".docx":
            continue
        # 跳过解压产物里的模板等
        rel_parts = f.relative_to(cwd).parts
        if rel_parts and rel_parts[0] in {"outputs", "inputs", "tools", "ocr_text"}:
            continue
        try:
            info = extract_docx_body(f)
        except zipfile.BadZipFile:
            docs.append({"file": f.as_posix(), "error": "非标准 OOXML，跳过"})
            continue

        rel = f.relative_to(cwd)
        md_path = ocr_root / f"{rel.as_posix()}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        body = info.pop("text", "") or ""
        header = f"# {rel.as_posix()}\n\n"
        md_path.write_text(header + body + ("\n" if body else ""), encoding="utf-8")
        chunk_n = _write_chunks(md_path, body)
        info["md_path"] = md_path.relative_to(cwd).as_posix()
        info["chunk_count"] = chunk_n
        # JSON 里不塞全文，避免过大
        info["preview"] = body[:800]
        docs.append(info)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"documents": docs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(out.relative_to(cwd).as_posix())


if __name__ == "__main__":
    main()

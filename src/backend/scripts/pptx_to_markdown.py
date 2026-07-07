"""
Convert PPTX to Markdown via LibreOffice (PPTX -> PDF) and Docling PDF OCR.

Used by ocr_pdf.py for slide decks with charts/images. Reads LIBREOFFICE_BIN and
PPTX_CONVERT_TIMEOUT_SEC from the environment (see app config Settings).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

_WATERMARK_LINE = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")
_IMAGE_ONLY = re.compile(r"^\s*<!--\s*image\s*-->\s*$", re.IGNORECASE)


def resolve_libreoffice_bin(explicit: Optional[str] = None) -> str:
    """Resolve soffice executable path."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return str(p.resolve())
        found = shutil.which(explicit)
        if found:
            return found
        raise FileNotFoundError(f"LibreOffice 未找到: {explicit}")

    env_bin = os.environ.get("LIBREOFFICE_BIN", "").strip()
    if env_bin:
        return resolve_libreoffice_bin(env_bin)

    for candidate in ("soffice", "/opt/homebrew/bin/soffice", "/usr/bin/soffice"):
        found = shutil.which(candidate) if "/" not in candidate else (
            candidate if Path(candidate).is_file() else None
        )
        if found:
            return found

    raise FileNotFoundError(
        "未找到 LibreOffice (soffice)。请安装 LibreOffice 并设置 LIBREOFFICE_BIN，"
        "例如 macOS: brew install --cask libreoffice"
    )


def _pptx_convert_timeout_sec() -> int:
    raw = os.environ.get("PPTX_CONVERT_TIMEOUT_SEC", "300").strip()
    try:
        return max(30, int(raw))
    except ValueError:
        return 300


def convert_pptx_to_pdf(
    pptx_path: Path,
    out_dir: Path,
    *,
    libreoffice_bin: Optional[str] = None,
    timeout_sec: Optional[int] = None,
) -> Path:
    """Run LibreOffice headless to produce a PDF next to out_dir."""
    pptx_path = pptx_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    soffice = resolve_libreoffice_bin(libreoffice_bin)
    timeout = timeout_sec if timeout_sec is not None else _pptx_convert_timeout_sec()

    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(pptx_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"LibreOffice 转换失败 (exit {proc.returncode}): {err or 'no output'}"
        )

    expected = out_dir / f"{pptx_path.stem}.pdf"
    if expected.is_file():
        return expected

    pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        raise RuntimeError(f"LibreOffice 未生成 PDF: {pptx_path}")
    return pdfs[0]


def clean_markdown(md: str) -> str:
    """Remove watermark lines and collapse empty image-only blocks."""
    lines: list[str] = []
    prev_image_only = False

    for line in md.splitlines():
        stripped = line.strip()
        if _WATERMARK_LINE.match(stripped):
            continue
        if _IMAGE_ONLY.match(line):
            if prev_image_only:
                continue
            prev_image_only = True
            lines.append(line)
            continue
        prev_image_only = False
        lines.append(line)

    text = "\n".join(lines)
    # Trim excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip() + "\n"


def markdown_with_page_sections(doc) -> str:
    """Export DoclingDocument with ## 第 N 页 per slide/page."""
    page_count = len(doc.pages) if getattr(doc, "pages", None) else 0
    if page_count <= 0:
        return clean_markdown(doc.export_to_markdown())

    sections: list[str] = []
    for page_no in range(1, page_count + 1):
        chunk = doc.export_to_markdown(page_no=page_no)
        chunk = clean_markdown(chunk)
        if not chunk.strip():
            continue
        sections.append(f"## 第 {page_no} 页\n\n{chunk.rstrip()}")

    if not sections:
        return clean_markdown(doc.export_to_markdown())
    return "\n\n".join(sections) + "\n"


def pptx_to_markdown(
    pptx_path: Path,
    converter: "DocumentConverter",
    *,
    libreoffice_bin: Optional[str] = None,
    convert_timeout_sec: Optional[int] = None,
    sidecar_path: Optional[Path] = None,
    source_rel: str = "",
    md_rel: str = "",
) -> str:
    """
    Convert a PPTX file to Markdown (LibreOffice -> PDF -> Docling OCR).
    """
    with tempfile.TemporaryDirectory(prefix="pptx_ocr_") as tmp:
        tmp_dir = Path(tmp)
        pdf_path = convert_pptx_to_pdf(
            pptx_path,
            tmp_dir,
            libreoffice_bin=libreoffice_bin,
            timeout_sec=convert_timeout_sec,
        )
        result = converter.convert(pdf_path)
        if sidecar_path is not None:
            from ocr_confidence_export import export_ocr_cells_sidecar

            export_ocr_cells_sidecar(
                result,
                sidecar_path,
                source_rel=source_rel or pptx_path.name,
                md_rel=md_rel,
            )
        return markdown_with_page_sections(result.document)

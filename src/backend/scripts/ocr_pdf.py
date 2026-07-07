"""
Batch convert PDF / PPTX under a project root using Docling (PDF uses RapidOCR).
PPTX: LibreOffice -> PDF -> Docling OCR. Outputs under ocr_text/ as .md files.
Run with conda v312:
  conda run -n v312 python scripts/ocr_pdf.py --root /path/to/extract
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from ocr_confidence_export import export_ocr_cells_sidecar  # noqa: E402
from pptx_to_markdown import pptx_to_markdown  # noqa: E402


def _should_skip(path: Path, root: Path) -> bool:
    p = str(path)
    if "__MACOSX" in p:
        return True
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = rel.parts
    if parts and parts[0] in ("ocr_text", "outputs", ".claude"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"root is not a directory: {root}", file=sys.stderr)
        return 1

    ocr_out = root / "ocr_text"
    ocr_out.mkdir(parents=True, exist_ok=True)

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        print(
            "docling import failed: {exc}\n"
            "Install in the SAME interpreter Celery uses, e.g.: pip install docling rapidocr onnxruntime\n"
            "Or set backend env OCR_PYTHON to that interpreter (see src/README.md).".format(
                exc=exc
            ),
            file=sys.stderr,
        )
        return 1

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.ocr_options = RapidOcrOptions()
    pipeline_options.generate_parsed_pages = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    sources = sorted(
        p
        for pattern in ("*.pdf", "*.pptx")
        for p in root.rglob(pattern)
        if not _should_skip(p, root)
    )
    pdf_count = sum(1 for p in sources if p.suffix.lower() == ".pdf")
    pptx_count = sum(1 for p in sources if p.suffix.lower() == ".pptx")
    print(
        f"Found {len(sources)} file(s) under {root} "
        f"({pdf_count} PDF, {pptx_count} PPTX)",
        flush=True,
    )

    errors = 0
    for src in sources:
        try:
            rel = src.relative_to(root)
            md_path = ocr_out / f"{rel.as_posix()}.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            rel_posix = rel.as_posix()
            md_rel = f"ocr_text/{rel_posix}.md"
            sidecar_path = ocr_out / f"{rel_posix}.ocr_cells.json"

            if src.suffix.lower() == ".pptx":
                md = pptx_to_markdown(
                    src,
                    converter,
                    sidecar_path=sidecar_path,
                    source_rel=rel_posix,
                    md_rel=md_rel,
                )
                md_path.write_text(md, encoding="utf-8")
                print(f"OK  pptx(via pdf) {rel}", flush=True)
            else:
                result = converter.convert(src)
                md = result.document.export_to_markdown()
                md_path.write_text(md, encoding="utf-8")
                n_cells = export_ocr_cells_sidecar(
                    result,
                    sidecar_path,
                    source_rel=rel_posix,
                    md_rel=md_rel,
                )
                print(f"OK  pdf {rel} ({n_cells} ocr cells)", flush=True)
        except Exception:  # noqa: BLE001
            errors += 1
            print(f"ERR {src}: {traceback.format_exc()}", file=sys.stderr, flush=True)

    if errors:
        print(f"Completed with {errors} error(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

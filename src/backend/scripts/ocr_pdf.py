"""
Batch convert PDF / PPTX under a project root using Docling (PDF uses RapidOCR).
PPTX: LibreOffice -> PDF -> Docling OCR. Outputs under ocr_text/ as .md files.
Run with conda v312:
  conda run -n v312 python scripts/ocr_pdf.py --root /path/to/extract
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import traceback
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from ocr_confidence_export import export_ocr_cells_sidecar  # noqa: E402
from ocr_meta import write_meta  # noqa: E402
from pptx_to_markdown import pptx_to_markdown  # noqa: E402
from table_split import describe as describe_split  # noqa: E402
from table_split import split_double_column_tables  # noqa: E402
from text_layer_guard import describe, inspect_text_layer  # noqa: E402


def _env_on(name: str) -> bool:
    return os.environ.get(name, "1").strip().lower() not in ("0", "false")


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

    def _build_converter(force_full_page_ocr: bool) -> "DocumentConverter":
        options = PdfPipelineOptions()
        options.do_ocr = True
        options.ocr_options = RapidOcrOptions()
        options.generate_parsed_pages = True
        if force_full_page_ocr:
            options.ocr_options.force_full_page_ocr = True
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    text_layer_guard = _env_on("OCR_TEXT_LAYER_GUARD")
    table_split = _env_on("OCR_TABLE_SPLIT")

    # 同一时刻只留一个转换器。docling 的模型是首次 convert 才实例化的，两个转换器
    # 各占一套 layout + TableFormer；2026-07-31 三文件那一跑因此涨到 6.68 GB 被 OOM。
    _current: dict[str, Any] = {"force": None, "conv": None}

    def _converter(force_full_page_ocr: bool) -> "DocumentConverter":
        if _current["conv"] is not None and _current["force"] == force_full_page_ocr:
            return _current["conv"]
        if _current["conv"] is not None:
            _current["conv"] = None
            gc.collect()
        _current["force"] = force_full_page_ocr
        _current["conv"] = _build_converter(force_full_page_ocr)
        return _current["conv"]

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

    # 先把所有 PDF 的文本层体检做完，再按「是否强制整页 OCR」分组处理，
    # 全程最多切换一次转换器，避免两套模型同时驻留。
    needs_force: dict[Path, bool] = {}
    if text_layer_guard:
        for src in sources:
            if src.suffix.lower() != ".pdf":
                continue
            report = inspect_text_layer(src)
            needs_force[src] = bool(report.get("untrustworthy"))
            print(f"    {src.relative_to(root)}: {describe(report)}", flush=True)

    # pptx 与普通 PDF 共用非强制转换器，排在前面；强制整页 OCR 的 PDF 殿后
    sources.sort(key=lambda p: needs_force.get(p, False))

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
                    _converter(False),
                    sidecar_path=sidecar_path,
                    source_rel=rel_posix,
                    md_rel=md_rel,
                )
                md_path.write_text(md, encoding="utf-8")
                print(f"OK  pptx(via pdf) {rel}", flush=True)
            else:
                result = _converter(needs_force.get(src, False)).convert(src)
                md = result.document.export_to_markdown()
                if table_split:
                    md, split_reports = split_double_column_tables(md)
                    if split_reports:
                        print(f"    {rel}: {describe_split(split_reports)}", flush=True)
                md_path.write_text(md, encoding="utf-8")
                n_cells = export_ocr_cells_sidecar(
                    result,
                    sidecar_path,
                    source_rel=rel_posix,
                    md_rel=md_rel,
                )
                del result
                print(f"OK  pdf {rel} ({n_cells} ocr cells)", flush=True)
        except Exception:  # noqa: BLE001
            errors += 1
            print(f"ERR {src}: {traceback.format_exc()}", file=sys.stderr, flush=True)
        # 每份文件的页图占几百 MB，多文件任务必须逐份回收，否则累加到 OOM
        gc.collect()

    if errors:
        print(f"Completed with {errors} error(s).", file=sys.stderr)
        return 1

    # 全部成功才留指纹；失败时不写，残缺产物自然不会被当成可复用
    write_meta(
        ocr_out,
        {"text_layer_guard": text_layer_guard, "table_split": table_split},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

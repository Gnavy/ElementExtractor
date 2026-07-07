#!/usr/bin/env python3
"""
从栅格图（jpg/png/webp 等）或 PDF 单页渲染图中裁剪矩形区域，保存为 PNG。
请在解压后的项目根目录下执行；路径均为相对当前工作目录。

依赖：Pillow；PDF 另需 PyMuPDF（import fitz）。

示例：
  python tools/crop_region.py --src 资料/身份证.jpg --out outputs/image_crops/id.png --bbox 120,80,380,260
  python tools/crop_region.py --src 资料/扫描.pdf --out outputs/image_crops/id.png --page 0 --bbox 40,60,500,320 --zoom 2
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path


def parse_bbox(s: str) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in s.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("bbox 须为四个整数：x,y,width,height（逗号分隔）")
    x, y, w, h = (int(a) for a in parts)
    if w <= 0 or h <= 0:
        raise ValueError("width、height 须为正整数")
    return x, y, w, h


def crop_raster(src: Path, out: Path, bbox: tuple[int, int, int, int]) -> None:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit(
            "缺少 Pillow：请先 pip install pillow\n"
        ) from e

    x, y, w, h = bbox
    im = Image.open(src)
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    crop = im.crop((x, y, x + w, y + h))
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, format="PNG")


def crop_pdf_page(
    src: Path,
    out: Path,
    bbox: tuple[int, int, int, int],
    page_index: int,
    zoom: float,
) -> None:
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except ImportError as e:
        raise SystemExit(
            "处理 PDF 需要 PyMuPDF 与 Pillow：pip install pymupdf pillow\n"
        ) from e

    doc = fitz.open(src)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise SystemExit(f"页码越界：{page_index}，文档共 {len(doc)} 页")
        page = doc.load_page(page_index)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # 不可直接用 pix.samples 喂 PIL：Pixmap 每行可能有 stride 对齐，会导致图像横向错位/“只剩一半宽”
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    finally:
        doc.close()

    x, y, w, h = bbox
    crop = img.crop((x, y, x + w, y + h))
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, format="PNG")


def main() -> None:
    p = argparse.ArgumentParser(description="裁剪图片或 PDF 页区域为 PNG")
    p.add_argument("--src", required=True, help="源文件相对路径")
    p.add_argument("--out", required=True, help="输出 PNG 相对路径")
    p.add_argument(
        "--bbox",
        required=True,
        help="裁剪矩形：x,y,width,height（像素，相对渲染后的图像）",
    )
    p.add_argument(
        "--page",
        type=int,
        default=0,
        help="PDF 页码（从 0 开始），栅格图忽略",
    )
    p.add_argument(
        "--zoom",
        type=float,
        default=2.0,
        help="PDF 渲染缩放（越大分辨率越高，bbox 相对于该渲染尺寸）",
    )
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    try:
        bbox = parse_bbox(args.bbox)
    except ValueError as e:
        raise SystemExit(str(e)) from e

    if not str(src).startswith(str(cwd)) or not str(out).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录之下")

    if not src.is_file():
        raise SystemExit(f"源文件不存在：{src}")

    suf = src.suffix.lower()
    if suf == ".pdf":
        crop_pdf_page(src, out, bbox, args.page, args.zoom)
    else:
        crop_raster(src, out, bbox)

    print(f"OK -> {out.relative_to(cwd)}", file=sys.stderr)


if __name__ == "__main__":
    main()

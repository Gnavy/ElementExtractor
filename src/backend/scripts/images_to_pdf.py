#!/usr/bin/env python3
"""
把材料里的图片转成 PDF，供现有 OCR 链路识别（docling 只扫 *.pdf / *.pptx）。

产出 outputs/image_pdf/<相对路径>.pdf。**输出目录必须在 outputs/ 下**，
ocr_pdf.py 跳过该目录，否则主 OCR 轮次会重复识别这些中间产物。

用法（cwd = extract_root）：
  python tools/images_to_pdf.py --src . --out outputs/image_pdf
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SKIP_DIRS = {"outputs", "inputs", "tools", "ocr_text"}
# 超大图先缩到这个长边，控制 OCR 内存
MAX_EDGE = 4000


def convert_one(src: Path, dst: Path) -> dict:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # 手机拍的证照常带旋转标记
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        elif im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        width, height = im.size
        if max(width, height) > MAX_EDGE:
            scale = MAX_EDGE / max(width, height)
            im = im.resize((int(width * scale), int(height * scale)))
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "PDF", resolution=200.0)
    return {"width": width, "height": height, "out_size": dst.stat().st_size}


def main() -> None:
    p = argparse.ArgumentParser(description="图片转 PDF")
    p.add_argument("--src", required=True, help="材料目录")
    p.add_argument("--out", required=True, help="输出目录，如 outputs/image_pdf")
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    if not str(src).startswith(str(cwd)) or not str(out).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录下")

    converted: list[dict] = []
    skipped: list[dict] = []
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        rel = f.relative_to(cwd)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        if "__MACOSX" in str(f) or f.name.startswith("."):
            continue
        dst = out / f"{rel.as_posix()}.pdf"
        try:
            info = convert_one(f, dst)
        except Exception as exc:  # noqa: BLE001 — 单张坏图不拖垮整批
            skipped.append({"file": rel.as_posix(), "reason": str(exc)[:200]})
            continue
        info["file"] = rel.as_posix()
        info["pdf"] = dst.relative_to(cwd).as_posix()
        converted.append(info)

    print(json.dumps({"converted": converted, "skipped": skipped}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
提取 ppt/pptx 每页文本，输出 JSON（供智能体理解指标定义与业务说明）。
仅依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A_NS, "p": P_NS}


def _slide_no(name: str) -> int:
    m = re.search(r"slide(\d+)\.xml$", name)
    return int(m.group(1)) if m else 10**9


def extract_ppt_text(path: Path) -> dict:
    out = {"file": path.as_posix(), "slides": []}
    with zipfile.ZipFile(path, "r") as zf:
        slides = [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        for s in sorted(slides, key=_slide_no):
            xml = ET.fromstring(zf.read(s))
            lines = []
            for t in xml.findall(".//a:t", NS):
                txt = (t.text or "").strip()
                if txt:
                    lines.append(txt)
            out["slides"].append({"slide_xml": s, "text": "\n".join(lines)})
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="提取 ppt/pptx 文本")
    p.add_argument("--src", required=True, help="pptx 文件或目录")
    p.add_argument("--out", required=True, help="输出 json")
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    if not str(src).startswith(str(cwd)) or not str(out).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录下")

    files = [src] if src.is_file() else sorted(src.rglob("*"))
    docs = []
    for f in files:
        if f.is_file() and f.suffix.lower() in {".pptx", ".ppt"}:
            try:
                docs.append(extract_ppt_text(f))
            except zipfile.BadZipFile:
                docs.append({"file": f.as_posix(), "error": "非标准 OOXML，跳过"})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"presentations": docs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.relative_to(cwd).as_posix())


if __name__ == "__main__":
    main()

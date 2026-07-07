#!/usr/bin/env python3
"""
提取 docx 中批注与正文片段，输出 JSON（供智能体理解指标口径/抽取规则）。
仅依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.findall(".//w:t", NS)).strip()


def extract_comments(docx_path: Path) -> dict:
    out: dict = {"file": docx_path.as_posix(), "comments": []}
    with zipfile.ZipFile(docx_path, "r") as zf:
        if "word/comments.xml" not in zf.namelist():
            return out
        comments_xml = ET.fromstring(zf.read("word/comments.xml"))
        comment_map: dict[str, dict] = {}
        for c in comments_xml.findall(".//w:comment", NS):
            cid = c.attrib.get(f"{{{W_NS}}}id", "")
            comment_map[cid] = {
                "id": cid,
                "author": c.attrib.get(f"{{{W_NS}}}author", ""),
                "date": c.attrib.get(f"{{{W_NS}}}date", ""),
                "comment": _text(c),
                "anchors": [],
            }

        if "word/document.xml" in zf.namelist():
            doc = ET.fromstring(zf.read("word/document.xml"))
            for p in doc.findall(".//w:p", NS):
                p_text = _text(p)
                for r in p.findall(".//w:commentRangeStart", NS):
                    cid = r.attrib.get(f"{{{W_NS}}}id", "")
                    if cid in comment_map and p_text:
                        comment_map[cid]["anchors"].append(p_text[:300])

        out["comments"] = list(comment_map.values())
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="提取 docx 批注")
    p.add_argument("--src", required=True, help="docx 文件或目录")
    p.add_argument("--out", required=True, help="输出 json")
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    src = (cwd / args.src).resolve()
    out = (cwd / args.out).resolve()
    if not str(src).startswith(str(cwd)) or not str(out).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录下")

    files = [src] if src.is_file() else sorted(src.rglob("*.docx"))
    rows = [extract_comments(f) for f in files if f.suffix.lower() == ".docx"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"documents": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.relative_to(cwd).as_posix())


if __name__ == "__main__":
    main()

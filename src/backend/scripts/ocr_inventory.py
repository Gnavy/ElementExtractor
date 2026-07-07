#!/usr/bin/env python3
"""
列出 ocr_text 下与司法/争议相关的 Markdown 路径，便于填报收集表时逐项对照。
默认：路径中包含任一关键词则收录（相对项目根的正斜杠路径）。
用法（cwd 为解压项目根）：
  python tools/ocr_inventory.py
  python tools/ocr_inventory.py --root ocr_text --out outputs/ocr_litigation_index.txt
  python tools/ocr_inventory.py --all-md   # 列出 root 下全部 .md
依赖：仅标准库。
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_KEYWORDS = (
    "诉讼",
    "保全",
    "裁定",
    "判决",
    "裁决",
    "受理",
    "执行",
    "仲裁",
    "调解",
    "起诉",
    "查封",
    "冻结",
    "破产",
    "清偿",
    "法院",
)


def main() -> None:
    p = argparse.ArgumentParser(description="列出 ocr_text 中与司法相关的 .md 路径")
    p.add_argument(
        "--root",
        default="ocr_text",
        help="起始目录（相对当前工作目录），默认 ocr_text",
    )
    p.add_argument(
        "--out",
        help="写入文件（UTF-8）；不传则打印到 stdout",
    )
    p.add_argument(
        "--all-md",
        action="store_true",
        help="不过滤关键词，列出 root 下全部 .md",
    )
    p.add_argument(
        "--keywords",
        nargs="*",
        default=list(DEFAULT_KEYWORDS),
        help="路径需包含其中任一子串（默认一组诉讼相关词）",
    )
    args = p.parse_args()

    cwd = Path.cwd().resolve()
    root = (cwd / args.root).resolve()
    if not str(root).startswith(str(cwd)):
        raise SystemExit("路径必须位于当前工作目录之下")
    if not root.is_dir():
        raise SystemExit(f"目录不存在：{root}")

    paths: list[str] = []
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(cwd).as_posix()
        if args.all_md:
            paths.append(rel)
            continue
        if any(k in rel for k in args.keywords):
            paths.append(rel)

    text = "\n".join(paths)
    if args.out:
        out_path = (cwd / args.out).resolve()
        if not str(out_path).startswith(str(cwd)):
            raise SystemExit("输出路径必须位于当前工作目录之下")
        out_path.parent.mkdir(parents=True, exist=True)
        out_path.write_text(text + ("\n" if text else ""), encoding="utf-8")
        print(str(Path(args.out).as_posix()))
    else:
        print(text)


if __name__ == "__main__":
    main()

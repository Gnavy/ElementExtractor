from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.agents.tools.script_runner import run_tool_script
from app.services.ocr_runner import run_ocr

_IMAGE_PDF_DIR = Path("outputs") / "image_pdf"


def _harvest_image_markdown(root: Path) -> int:
    """图片 PDF 的 OCR 结果搬回主 ocr_text，按原图路径命名。"""
    staged = root / _IMAGE_PDF_DIR / "ocr_text"
    if not staged.is_dir():
        return 0
    moved = 0
    for md in staged.rglob("*.pdf.md"):
        rel = md.relative_to(staged).as_posix()[: -len(".pdf.md")]
        target = root / "ocr_text" / f"{rel}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, target)
        moved += 1
    return moved


def index_extra_materials_node(state: dict[str, Any]) -> dict[str, Any]:
    """case0 专属：补 index_materials_node 没覆盖的 Excel 与图片。

    不并进 index_materials_node——那个节点 case1 也在用，加东西会改它的语料构成。
    """
    root = Path(state["extract_root"])
    task_kind = str(state.get("task_kind") or "")
    logs: list[str] = []

    ok_xls, log_xls = run_tool_script(
        root,
        "extract_excel_text.py",
        ["--src", ".", "--out", "outputs/excel_text_index.json"],
        timeout=300,
    )
    logs.append("excel_text_index OK" if ok_xls else f"excel index: {log_xls[:150]}")

    ok_img, log_img = run_tool_script(
        root,
        "images_to_pdf.py",
        ["--src", ".", "--out", _IMAGE_PDF_DIR.as_posix()],
        timeout=300,
    )
    n_pdf = 0
    if ok_img:
        try:
            n_pdf = len(json.loads(log_img.strip().splitlines()[-1]).get("converted") or [])
        except (ValueError, IndexError):
            n_pdf = 0
    logs.append(f"图片转 PDF {n_pdf} 张" if ok_img else f"images_to_pdf: {log_img[:150]}")

    if n_pdf:
        # 只对 image_pdf 子目录跑，主轮次扫不到 outputs/ 下的东西
        code, ocr_log = run_ocr(
            root / _IMAGE_PDF_DIR,
            log_path=root / "outputs" / "image_ocr.log",
            task_kind=task_kind,
        )
        if code == 0:
            logs.append(f"图片 OCR 完成，回收 md {_harvest_image_markdown(root)} 份")
        else:
            logs.append(f"图片 OCR 失败(code={code}): {ocr_log[-150:]}")

    return {"log_lines": logs, "progress": "补充材料索引完成"}

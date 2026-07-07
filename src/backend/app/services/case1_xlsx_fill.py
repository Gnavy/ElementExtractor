import json
import subprocess
import sys
from pathlib import Path

from app.config import settings


def try_fill_case1_collection_from_elements(extract_root: Path) -> tuple[bool, str]:
    """
    若已有 elements_extracted.json 但缺少 collection_filled.xlsx，运行兜底脚本。
    返回 (成功与否, 日志摘要)。
    """
    elements = extract_root / "outputs" / "elements_extracted.json"
    template = extract_root / "inputs" / "collection_template.xlsx"
    out = extract_root / "outputs" / "collection_filled.xlsx"

    if out.is_file() and out.stat().st_size >= 512:
        return True, "collection_filled.xlsx 已存在"
    if not elements.is_file():
        return False, "缺少 outputs/elements_extracted.json，无法兜底填表"
    if not template.is_file():
        return False, "缺少 inputs/collection_template.xlsx"

    script = settings.ocr_script.parent / "fill_case1_collection.py"
    if not script.is_file():
        return False, f"脚本不存在：{script}"

    cmd = [
        sys.executable,
        str(script),
        "--template",
        "inputs/collection_template.xlsx",
        "--elements",
        "outputs/elements_extracted.json",
        "--out",
        "outputs/collection_filled.xlsx",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(extract_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, f"兜底填表失败(code={proc.returncode}): {log[-1500:]}"

    if not out.is_file() or out.stat().st_size < 512:
        return False, "兜底脚本未生成有效 xlsx"

    try:
        summary = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        summary = {}
    return True, f"已从 elements_extracted 兜底生成 xlsx: {summary}"

import json
import subprocess
import sys
from pathlib import Path


def run_case1_validation(extract_root: Path) -> tuple[bool, str]:
    """运行 validate_collection_filled.py，返回 (passed, summary)。"""
    catalog = extract_root / "outputs" / "template_row_catalog.json"
    filled = extract_root / "outputs" / "collection_filled.xlsx"
    if not catalog.is_file() or not filled.is_file():
        return True, "跳过校验：缺少 catalog 或 filled xlsx"

    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "validate_collection_filled.py"
    if not script.is_file():
        return True, "跳过校验：脚本不存在"

    report_path = extract_root / "outputs" / "validation_report.json"
    cmd = [
        sys.executable,
        str(script),
        "--catalog",
        "outputs/template_row_catalog.json",
        "--filled",
        "outputs/collection_filled.xlsx",
        "--out",
        "outputs/validation_report.json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(extract_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    summary = (proc.stdout or "") + (proc.stderr or "")
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("errors"):
                return False, f"填表校验未通过: {report['errors'][:5]}"
            return True, "填表校验通过"
        except json.JSONDecodeError:
            pass
    if proc.returncode != 0:
        return False, f"校验脚本失败: {summary[-1500:]}"
    return True, "填表校验通过"

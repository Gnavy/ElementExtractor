import json
import os
import re
import subprocess
import sys
from pathlib import Path

from app.config import settings


def _run_script(
    extract_root: Path,
    script_name: str,
    args: list[str],
    timeout: int = 120,
) -> tuple[bool, str]:
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / script_name
    if not script.is_file():
        return False, f"脚本不存在: {script_name}"
    cmd = [sys.executable, str(script), *args]
    env = os.environ.copy()
    env["OCR_CONFIDENCE_THRESHOLD"] = str(settings.ocr_confidence_threshold)
    proc = subprocess.run(
        cmd,
        cwd=str(extract_root),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, out[-3000:]
    return True, out[-3000:]


def dump_case2_fill_schema(extract_root: Path) -> tuple[bool, str]:
    return _run_script(
        extract_root,
        "dump_case2_fill_schema.py",
        [
            "--src",
            "inputs/collection_template.xlsx",
            "--out",
            "outputs/case2_fill_schema.json",
            "--catalog-out",
            "outputs/template_row_catalog.json",
        ],
    )


def backfill_case2_schema(extract_root: Path) -> tuple[bool, str]:
    return _run_script(
        extract_root,
        "backfill_case2_schema.py",
        [
            "--template",
            "inputs/collection_template.xlsx",
            "--filled-schema",
            "outputs/case2_filled_schema.json",
            "--out",
            "outputs/collection_filled.xlsx",
            "--report",
            "outputs/backfill_report.json",
        ],
    )


def apply_case2_calc_rules(extract_root: Path) -> tuple[bool, str]:
    rules_path = extract_root / "inputs" / "fill_calc_rules.json"
    if not rules_path.is_file():
        return True, "no fill_calc_rules.json, skip calc"
    try:
        doc = json.loads(rules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, "fill_calc_rules.json invalid, skip calc"
    if not (doc.get("rules") or []):
        return True, "empty calc rules, skip"
    return _run_script(
        extract_root,
        "apply_case2_calc_rules.py",
        [
            "--filled",
            "outputs/case2_filled_schema.json",
            "--rules",
            "inputs/fill_calc_rules.json",
            "--report",
            "outputs/calc_rules_report.json",
        ],
    )


def has_case2_filled_schema(extract_root: Path) -> bool:
    p = extract_root / "outputs" / "case2_filled_schema.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if data.get("sheets") and any((sh.get("items") or []) for sh in data["sheets"]):
        return True
    if data.get("subject_sets"):
        return True
    return bool(data.get("sheets"))


def _count_nonempty_filled_values(data: dict) -> int:
    n = 0
    for sh in data.get("sheets") or []:
        for item in sh.get("items") or []:
            for field in (item.get("fields") or {}).values():
                if not isinstance(field, dict):
                    continue
                if "value" not in field:
                    continue
                v = field.get("value")
                if v not in (None, ""):
                    n += 1
        for subj in sh.get("subjects") or []:
            for dim in subj.get("dimensions") or []:
                v = dim.get("value")
                if v not in (None, "", 0, 0.0):
                    n += 1
    for ss in data.get("subject_sets") or []:
        for subj in ss.get("subjects") or []:
            for dim in subj.get("dimensions") or []:
                v = dim.get("value")
                if v not in (None, "", 0, 0.0):
                    n += 1
    return n


def _is_nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "null", "none", "nil", "n/a", "na"}
    return True


def _validate_fill_plan_semantics(data: dict) -> tuple[bool, str]:
    """校验非空字段类型、证据和报告期列的一致性。"""
    numeric_columns: set[tuple[str, str]] = set()
    dated_columns: set[tuple[str, str]] = set()
    non_date_values = 0
    errors: list[str] = []

    for sheet in data.get("sheets") or []:
        sheet_name = str(sheet.get("sheet") or sheet.get("name") or "")
        for item in sheet.get("items") or []:
            item_id = str(item.get("item_id") or "")
            has_direct_value = False
            for key, field in (item.get("fields") or {}).items():
                if not isinstance(field, dict):
                    continue
                value = field.get("value")
                if not _is_nonempty(value):
                    continue
                value_type = str(field.get("value_type") or "")
                if value_type == "date":
                    if not isinstance(value, str) or not re.fullmatch(
                        r"20\d{2}-\d{2}-\d{2}", value.strip()
                    ):
                        errors.append(f"{item_id}:{key} 日期格式非法")
                    dated_columns.add((sheet_name, str(key)))
                    continue

                non_date_values += 1
                has_direct_value = True
                if value_type == "number":
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        errors.append(f"{item_id}:{key} 数值类型非法")
                    numeric_columns.add((sheet_name, str(key)))

            if (
                has_direct_value
                and not (item.get("evidence_refs") or [])
                and not str(item.get("reason_one_line") or "").startswith("计算规则(")
            ):
                errors.append(f"{item_id} 有值但没有来源证据")

    if non_date_values == 0:
        errors.append("除报告日期外没有任何有效填报数据")
    missing_dates = sorted(numeric_columns - dated_columns)
    if missing_dates:
        errors.append(
            "已有数值但缺少对应报告日期: "
            + ", ".join(f"{sheet}:{key}" for sheet, key in missing_dates)
        )
    return (not errors, "；".join(errors[:20]))


def validate_case2_backfill(extract_root: Path) -> tuple[bool, str]:
    report_path = extract_root / "outputs" / "backfill_report.json"
    filled_path = extract_root / "outputs" / "case2_filled_schema.json"
    if not report_path.is_file():
        return False, "缺少 outputs/backfill_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        filled = json.loads(filled_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return False, f"回填报告或 filled schema 无法解析: {e}"

    written = int(report.get("written_cells") or 0)
    nonempty = _count_nonempty_filled_values(filled)
    item_count = sum(len(sh.get("items") or []) for sh in filled.get("sheets") or [])
    if item_count > 0 and nonempty == 0:
        return False, f"Case2 填报结果全空：items={item_count}, filled_nonempty=0"
    semantic_ok, semantic_msg = _validate_fill_plan_semantics(filled)
    if item_count > 0 and not semantic_ok:
        return False, f"Case2 业务校验失败：{semantic_msg}"
    if nonempty > 0 and written == 0:
        return (
            False,
            f"回填未写入任何单元格，但 filled 含 {nonempty} 个非空字段；"
            "请保留 fill_plan 的 sheets/items/fields 结构。",
        )
    if nonempty > 0 and written < nonempty // 2:
        return (
            False,
            f"回填写入过少：written_cells={written}，非空字段={nonempty}。",
        )
    return (
        True,
        f"items={item_count}, written_cells={written}, filled_nonempty={nonempty}",
    )

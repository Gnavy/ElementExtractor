import json
from pathlib import Path
from typing import Optional


def write_task_meta(
    extract_root: Path,
    *,
    task_id: str,
    classification_basis: str,
    extract_schema: str,
    collection_template_path: Optional[str] = None,
    collection_template_format: Optional[str] = None,
    task_kind: Optional[str] = None,
    indicator_judgment_rules: Optional[str] = None,
    fill_logic_rules: Optional[str] = None,
) -> Path:
    meta = {
        "task_id": task_id,
        "classification_basis": classification_basis,
        "extract_schema": extract_schema,
    }
    if task_kind:
        meta["task_kind"] = task_kind
    if indicator_judgment_rules and indicator_judgment_rules.strip():
        meta["indicator_judgment_rules"] = indicator_judgment_rules.strip()
    if fill_logic_rules and fill_logic_rules.strip():
        preview = fill_logic_rules.strip()
        if len(preview) > 3000:
            preview = preview[:3000] + "\n…（全文见 inputs/fill_logic_rules.md）"
        meta["fill_logic_rules"] = preview
    if collection_template_path:
        meta["collection_template_path"] = collection_template_path
    if collection_template_format:
        meta["collection_template_format"] = collection_template_format
    path = extract_root / ".task-meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

import shutil
from pathlib import Path

TOOL_SCRIPTS = (
    "crop_region.py",
    "dump_sheet_headers.py",
    "dump_collection_template.py",
    "dump_collection_template_generic.py",
    "dump_case2_fill_schema.py",
    "backfill_case2_schema.py",
    "parse_case2_calc_rules.py",
    "apply_case2_calc_rules.py",
    "ocr_inventory.py",
    "extract_docx_comments.py",
    "extract_docx_text.py",
    "extract_pptx_text.py",
    "fill_case1_collection.py",
    "validate_collection_filled.py",
    "tavily_search.py",
)


def copy_task_tools_to_extract(extract_root: Path) -> None:
    """
    Copy helper scripts into extract_root/tools/ for local debugging / deterministic tools.
    """
    backend_dir = Path(__file__).resolve().parent.parent.parent
    dest_dir = extract_root / "tools"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in TOOL_SCRIPTS:
        src = backend_dir / "scripts" / name
        if src.is_file():
            shutil.copy2(src, dest_dir / name)

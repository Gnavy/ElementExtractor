import shutil
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings


def ensure_storage() -> None:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.extracts_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)


def task_extract_dir(task_id: str) -> Path:
    return settings.extracts_dir / task_id


def task_upload_zip(task_id: str, original_name: str) -> Path:
    return settings.uploads_dir / f"{task_id}_{original_name}"


def task_upload_collection_storage(task_id: str, suffix: str) -> Path:
    """suffix 含点号，如 .xlsx / .xlsm"""
    return settings.uploads_dir / f"{task_id}_collection{suffix}"


def copy_collection_template_into_extract(
    task_id: str,
    collection_original_filename: Optional[str],
    extract_root: Path,
) -> Tuple[Optional[str], Optional[str]]:
    """
    将 uploads 中的信息收集表复制到 extract_root/inputs/collection_template.{ext}。
    返回 (相对路径, format:xlsx|xlsm)；若无模板则 (None, None)。
    """
    if not collection_original_filename:
        return None, None
    suf = Path(collection_original_filename).suffix.lower()
    if suf not in (".xlsx", ".xlsm"):
        return None, None
    src = task_upload_collection_storage(task_id, suf)
    if not src.is_file():
        return None, None
    dest_dir = extract_root / "inputs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"collection_template{suf}"
    shutil.copy2(src, dest)
    rel = f"inputs/collection_template{suf}"
    fmt = "xlsm" if suf == ".xlsm" else "xlsx"
    return rel, fmt

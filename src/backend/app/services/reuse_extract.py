"""
相同 ZIP（MD5）时复用历史任务的解压目录与 OCR 结果；不复制 outputs/。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import shutil
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task
from app.services.paths import task_extract_dir

ACTIVE_STATUSES = frozenset(
    {"PENDING", "EXTRACTING", "OCR_RUNNING", "AGENT_RUNNING"}
)


def extract_has_ocr_markdown(root: Path) -> bool:
    ocr = root / "ocr_text"
    if not ocr.is_dir():
        return False
    return any(ocr.rglob("*.md"))


def copy_extract_skip_outputs(src: Path, dst: Path) -> None:
    """复制解压内容，忽略 outputs/，供新任务重新跑智能体。"""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    if not src.is_dir():
        return
    for child in src.iterdir():
        if child.name == "outputs":
            continue
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def find_reusable_extract(
    db: Session, zip_md5: str, exclude_task_id: str
) -> Tuple[Optional[Path], bool]:
    """
    返回 (历史解压目录, 是否可跳过 OCR)。
    跳过仍在进行中的任务；源目录需非空。
    """
    stmt = (
        select(Task)
        .where(Task.zip_md5 == zip_md5, Task.id != exclude_task_id)
        .order_by(Task.created_at.desc())
    )
    for t in db.scalars(stmt).all():
        if t.status in ACTIVE_STATUSES:
            continue
        root = task_extract_dir(t.id)
        if not root.is_dir():
            continue
        try:
            if not any(root.iterdir()):
                continue
        except OSError:
            continue
        skip_ocr = extract_has_ocr_markdown(root)
        return root, skip_ocr
    return None, False

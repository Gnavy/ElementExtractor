"""
相同 ZIP（MD5）时复用历史任务的解压目录与 OCR 结果；不复制 outputs/。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import shutil
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Task
from app.services.paths import task_extract_dir


def _ocr_meta_module():
    """scripts/ocr_meta.py 由 OCR 子进程与本进程共用，按需加进 sys.path"""
    import sys

    scripts_dir = str(settings.ocr_script.resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import ocr_meta

    return ocr_meta

ACTIVE_STATUSES = frozenset(
    {"PENDING", "EXTRACTING", "OCR_RUNNING", "AGENT_RUNNING"}
)


_OCR_SOURCE_EXT = frozenset({".pdf", ".pptx"})
_SKIP_DIRS = frozenset({"ocr_text", "outputs", ".claude"})


def _ocr_sources(root: Path) -> list[Path]:
    """待 OCR 的源文件，口径与 scripts/ocr_pdf.py 保持一致"""
    out = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _OCR_SOURCE_EXT:
            continue
        rel = path.relative_to(root)
        if "__MACOSX" in str(path) or (rel.parts and rel.parts[0] in _SKIP_DIRS):
            continue
        out.append(path)
    return out


def extract_has_ocr_markdown(root: Path) -> bool:
    """每个待 OCR 的源文件都有对应 md 才算完整。

    原来只要有任意一份 md 就当「已 OCR」，于是 OCR 中途失败留下的残缺产物
    会被后续同材料任务复用并跳过 OCR，缺的那几份再也补不上。
    """
    ocr = root / "ocr_text"
    if not ocr.is_dir():
        return False
    sources = _ocr_sources(root)
    if not sources:
        return False
    return all(
        (ocr / f"{p.relative_to(root).as_posix()}.md").is_file() for p in sources
    )


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


def ocr_produced_by_current_code(root: Path, switches: Optional[dict]) -> bool:
    """历史 ocr_text 是否由当前这版 OCR 代码和开关产出。

    switches 传 None 表示不校验（供不关心 OCR 版本的调用方使用）。
    """
    if switches is None:
        return True
    try:
        return _ocr_meta_module().meta_matches(root / "ocr_text", switches)
    except Exception:  # noqa: BLE001 — 取不到指纹就当不可复用，安全方向
        return False


def find_reusable_extract(
    db: Session,
    zip_md5: str,
    exclude_task_id: str,
    expected_ocr: Optional[dict] = None,
) -> Tuple[Optional[Path], bool]:
    """
    返回 (历史解压目录, 是否可跳过 OCR)。
    跳过仍在进行中的任务；源目录需非空。
    expected_ocr 给出当前生效的 OCR 开关，指纹对不上就不跳过 OCR。
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
        skip_ocr = extract_has_ocr_markdown(root) and ocr_produced_by_current_code(
            root, expected_ocr
        )
        return root, skip_ocr
    return None, False

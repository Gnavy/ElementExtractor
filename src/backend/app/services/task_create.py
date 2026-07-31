import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Task, TaskStatus
from app.services.case1_defaults import (
    CASE1_CLASSIFICATION_BASIS,
    CASE1_COLLECTION_TEMPLATE_DISPLAY_NAME,
    case1_extract_schema_json,
)
from app.services.case2_defaults import (
    CASE2_CLASSIFICATION_BASIS,
    MAX_FILL_LOGIC_RULES_LEN,
    case2_extract_schema_json,
)
from app.services.paths import ensure_storage, task_upload_collection_storage, task_upload_zip
from app.services.unzip_service import repair_zip_name
from app.services.upload_zip_builder import build_zip_from_pairs, zip_entry
from app.worker_tasks import process_review_task

MAX_INDICATOR_JUDGMENT_RULES_LEN = 8000

_COLLECTION_EXT = frozenset({".xlsx", ".xlsm"})

EMPTY_EXTRACT_SCHEMA = '{"fields":[]}'

_CASE1_SUPPLEMENT_EXT = frozenset(
    {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xlsm", ".xls", ".txt", ".md"}
)

_CASE2_SOURCE_EXT = frozenset(
    {
        ".pdf",
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".xlsx",
        ".xlsm",
        ".xls",
        ".csv",
        ".txt",
        ".md",
        ".jpg",
        ".jpeg",
        ".png",
    }
)


def form_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _safe_zip_folder_name(value: str, fallback: str) -> str:
    # 先还原再截断，否则会把汉字切成半个
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", repair_zip_name(value)).strip(" .")
    return cleaned[:100] or fallback


def _unique_zip_path(path: str, used: set[str]) -> str:
    candidate = path
    stem = str(Path(path).with_suffix(""))
    suffix = Path(path).suffix
    index = 2
    while candidate in used:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _safe_archive_part(value: str, fallback: str) -> str:
    # 先还原再截断，同 _safe_zip_folder_name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", repair_zip_name(value)).strip(" .")
    return cleaned[:100] or fallback


def _safe_archive_path(parts: tuple[str, ...], fallback: str) -> str:
    safe_parts = [
        _safe_archive_part(part, f"folder_{idx}")
        for idx, part in enumerate(parts)
        if part not in ("", ".", "..")
    ]
    if not safe_parts:
        safe_parts = [fallback]
    return "/".join(safe_parts)


def write_general_upload_zip(
    dest_zip: Path,
    uploads: list[tuple[str, bytes]],
    *,
    max_bytes: int,
) -> None:
    used: set[str] = set()
    written_bytes = 0
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
        for upload_index, (filename, data) in enumerate(
            sorted(uploads, key=lambda pair: Path(pair[0]).name), start=1
        ):
            safe_name = Path(filename).name or f"材料_{upload_index}"
            if safe_name.lower().endswith(".zip"):
                try:
                    in_zip = zipfile.ZipFile(io.BytesIO(data), "r")
                except zipfile.BadZipFile as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{safe_name} 不是有效的压缩包文件",
                    ) from exc
                folder = _safe_zip_folder_name(Path(safe_name).stem, f"压缩包_{upload_index}")
                with in_zip:
                    for info in in_zip.infolist():
                        raw_parts = Path(info.filename).parts
                        if (
                            info.is_dir()
                            or not raw_parts
                            or raw_parts[0] == "__MACOSX"
                            or Path(info.filename).name == ".DS_Store"
                            or any(part in ("", ".", "..") for part in raw_parts)
                            or Path(info.filename).is_absolute()
                        ):
                            continue
                        content = in_zip.read(info)
                        written_bytes += len(content)
                        if written_bytes > max_bytes:
                            raise HTTPException(
                                status_code=400,
                                detail=f"上传材料总大小超过 {settings.max_zip_mb} MB 限制",
                            )
                        inner_path = _safe_archive_path(raw_parts, f"文件_{upload_index}")
                        archive_name = _unique_zip_path(f"sources/{folder}/{inner_path}", used)
                        out_zip.writestr(zip_entry(archive_name), content)
            else:
                written_bytes += len(data)
                if written_bytes > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"上传材料总大小超过 {settings.max_zip_mb} MB 限制",
                    )
                archive_name = _unique_zip_path(
                    f"sources/{_safe_archive_part(safe_name, f'材料_{upload_index}')}",
                    used,
                )
                out_zip.writestr(zip_entry(archive_name), data)


def create_general_task(
    db: Session,
    *,
    upload_pairs: list[tuple[str, bytes]],
    classification_basis: str,
    extract_schema: str,
    collection_template_bytes: Optional[tuple[str, bytes]] = None,
    run_ocr: bool = True,
    run_agent: bool = True,
    run_collection_fill: bool = True,
    enqueue: bool = True,
) -> Task:
    return _create_material_review_task(
        db,
        task_kind="general",
        upload_pairs=upload_pairs,
        classification_basis=classification_basis,
        extract_schema=extract_schema,
        collection_template_bytes=collection_template_bytes,
        run_ocr=run_ocr,
        run_agent=run_agent,
        run_collection_fill=run_collection_fill,
        enqueue=enqueue,
    )


def create_classification_task(
    db: Session,
    *,
    upload_pairs: list[tuple[str, bytes]],
    classification_basis: str,
    run_ocr: bool = True,
    enqueue: bool = True,
) -> Task:
    if not classification_basis.strip():
        raise HTTPException(status_code=400, detail="classification 任务须提供 classification_basis")
    return _create_material_review_task(
        db,
        task_kind="classification",
        upload_pairs=upload_pairs,
        classification_basis=classification_basis,
        extract_schema=EMPTY_EXTRACT_SCHEMA,
        collection_template_bytes=None,
        run_ocr=run_ocr,
        run_agent=True,
        run_collection_fill=False,
        enqueue=enqueue,
    )


def create_extraction_task(
    db: Session,
    *,
    upload_pairs: list[tuple[str, bytes]],
    extract_schema: str,
    classification_basis: str = "",
    run_ocr: bool = True,
    enqueue: bool = True,
) -> Task:
    if not extract_schema.strip():
        raise HTTPException(status_code=400, detail="extraction 任务须提供 extract_schema")
    try:
        json.loads(extract_schema)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"extract_schema 必须是合法 JSON 字符串: {exc}"
        ) from exc
    return _create_material_review_task(
        db,
        task_kind="extraction",
        upload_pairs=upload_pairs,
        classification_basis=classification_basis.strip() or "（要素抽取任务，无分类依据）",
        extract_schema=extract_schema,
        collection_template_bytes=None,
        run_ocr=run_ocr,
        run_agent=True,
        run_collection_fill=False,
        enqueue=enqueue,
    )


def _create_material_review_task(
    db: Session,
    *,
    task_kind: str,
    upload_pairs: list[tuple[str, bytes]],
    classification_basis: str,
    extract_schema: str,
    collection_template_bytes: Optional[tuple[str, bytes]],
    run_ocr: bool,
    run_agent: bool,
    run_collection_fill: bool,
    enqueue: bool,
) -> Task:
    ensure_storage()
    if not upload_pairs:
        raise HTTPException(status_code=400, detail="请上传至少一个材料文件")

    try:
        json.loads(extract_schema)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"extract_schema 必须是合法 JSON 字符串: {exc}"
        ) from exc

    if not run_ocr and not run_agent:
        raise HTTPException(
            status_code=400,
            detail="请至少选择「扫描件识别」或「材料分类与要素整理」之一",
        )

    max_bytes = settings.max_zip_mb * 1024 * 1024
    original_names = [name for name, _ in upload_pairs]
    display_name = (
        Path(original_names[0]).name
        if len(original_names) == 1
        else f"多文件材料包_{len(original_names)}个文件.zip"
    )

    task = Task(
        task_kind=task_kind,
        classification_basis=classification_basis,
        extract_schema=extract_schema,
        zip_filename=display_name,
        status=TaskStatus.PENDING.value,
        progress_message="已排队",
        run_ocr=run_ocr,
        run_agent=run_agent,
        run_collection_fill=run_collection_fill,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    dest = task_upload_zip(task.id, f"materials_{task.id}.zip")
    write_general_upload_zip(dest, upload_pairs, max_bytes=max_bytes)
    task.zip_path = str(dest)
    task.zip_md5 = hashlib.md5(dest.read_bytes()).hexdigest()

    coll_name: Optional[str] = None
    if collection_template_bytes is not None:
        cfn, cbytes = collection_template_bytes
        suf = Path(cfn).suffix.lower()
        if suf not in _COLLECTION_EXT:
            raise HTTPException(status_code=400, detail="信息收集表须为 .xlsx 或 .xlsm")
        max_c = settings.max_collection_mb * 1024 * 1024
        if len(cbytes) > max_c:
            raise HTTPException(
                status_code=400,
                detail=f"信息收集表超过 {settings.max_collection_mb} MB 限制",
            )
        cdest = task_upload_collection_storage(task.id, suf)
        cdest.write_bytes(cbytes)
        coll_name = cfn

    task.collection_template_original_filename = coll_name
    db.commit()

    if enqueue:
        process_review_task.delay(task.id)
    return task


def create_case1_task(
    db: Session,
    *,
    docx_name: str,
    docx_bytes: bytes,
    supplements: list[tuple[str, bytes]],
    run_ocr: bool = True,
    indicator_judgment_rules: str = "",
    enqueue: bool = True,
) -> Task:
    ensure_storage()
    if not docx_name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="主文件须为 .docx 格式")

    max_bytes = settings.max_zip_mb * 1024 * 1024
    if len(docx_bytes) > max_bytes:
        raise HTTPException(status_code=400, detail=f"docx 超过 {settings.max_zip_mb} MB 限制")

    rules_text = indicator_judgment_rules.strip()
    if len(rules_text) > MAX_INDICATOR_JUDGMENT_RULES_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"指标判断规则超过 {MAX_INDICATOR_JUDGMENT_RULES_LEN} 字符限制",
        )

    if not settings.case1_template_path.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"内置 Case1 模板缺失: {settings.case1_template_path}",
        )

    task = Task(
        task_kind="case1",
        source_docx_filename=docx_name,
        classification_basis=CASE1_CLASSIFICATION_BASIS,
        extract_schema=case1_extract_schema_json(),
        zip_filename=f"{docx_name}.zip",
        status=TaskStatus.PENDING.value,
        progress_message="已排队",
        run_ocr=run_ocr,
        run_agent=True,
        run_collection_fill=True,
        collection_template_original_filename=CASE1_COLLECTION_TEMPLATE_DISPLAY_NAME,
        indicator_judgment_rules=rules_text or None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    zip_dest = task_upload_zip(task.id, f"case1_{task.id}.zip")
    build_zip_from_pairs(
        zip_dest,
        root_file=(docx_name, docx_bytes),
        extras=supplements,
        extras_prefix="supplements",
    )
    task.zip_md5 = hashlib.md5(zip_dest.read_bytes()).hexdigest()
    task.zip_path = str(zip_dest)
    task.zip_filename = docx_name

    coll_dest = task_upload_collection_storage(task.id, ".xlsx")
    shutil.copy2(settings.case1_template_path, coll_dest)

    db.commit()

    if enqueue:
        process_review_task.delay(task.id)
    return task


def create_case2_task(
    db: Session,
    *,
    src_pairs: list[tuple[str, bytes]],
    template_name: str,
    template_bytes: bytes,
    run_ocr: bool = True,
    fill_logic_rules: str = "",
    enqueue: bool = True,
) -> Task:
    ensure_storage()
    if not src_pairs:
        raise HTTPException(status_code=400, detail="请至少上传 1 个源文件")

    tpl_suf = Path(template_name).suffix.lower()
    if tpl_suf not in (".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="模板须为 .xlsx 或 .xlsm")

    max_bytes = settings.max_zip_mb * 1024 * 1024
    max_tpl = settings.max_collection_mb * 1024 * 1024
    if len(template_bytes) > max_tpl:
        raise HTTPException(status_code=400, detail=f"模板超过 {settings.max_collection_mb} MB 限制")

    rules_text = fill_logic_rules.strip()
    if len(rules_text) > MAX_FILL_LOGIC_RULES_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"填表规则超过 {MAX_FILL_LOGIC_RULES_LEN} 字限制",
        )

    task = Task(
        task_kind="case2",
        source_docx_filename=src_pairs[0][0],
        classification_basis=CASE2_CLASSIFICATION_BASIS,
        extract_schema=case2_extract_schema_json(),
        zip_filename=f"case2_{src_pairs[0][0]}",
        status=TaskStatus.PENDING.value,
        progress_message="已排队",
        run_ocr=run_ocr,
        run_agent=True,
        run_collection_fill=True,
        collection_template_original_filename=template_name,
        fill_logic_rules=rules_text or None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    zip_dest = task_upload_zip(task.id, f"case2_{task.id}.zip")
    build_zip_from_pairs(zip_dest, extras=src_pairs, extras_prefix="sources")
    task.zip_md5 = hashlib.md5(zip_dest.read_bytes()).hexdigest()
    task.zip_path = str(zip_dest)
    task.zip_filename = Path(task.zip_filename).name

    coll_dest = task_upload_collection_storage(task.id, tpl_suf)
    coll_dest.write_bytes(template_bytes)

    db.commit()

    if enqueue:
        process_review_task.delay(task.id)
    return task


def validate_case1_supplements(supplements: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], bool]:
    """返回 (校验后的补充文件, 是否建议/需要 OCR：含 PDF 或 PPTX)。"""
    max_bytes = settings.max_zip_mb * 1024 * 1024
    needs_ocr = False
    validated: list[tuple[str, bytes]] = []
    for name, data in supplements:
        suf = Path(name).suffix.lower()
        if suf not in _CASE1_SUPPLEMENT_EXT:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的补充文件类型: {name}（允许 {_CASE1_SUPPLEMENT_EXT}）",
            )
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"补充文件 {name} 过大")
        validated.append((name, data))
        if suf in {".pdf", ".pptx", ".ppt"}:
            needs_ocr = True
    return validated, needs_ocr


def validate_case2_sources(src_pairs: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], bool]:
    max_bytes = settings.max_zip_mb * 1024 * 1024
    has_pdf = False
    validated: list[tuple[str, bytes]] = []
    for name, data in src_pairs:
        suf = Path(name).suffix.lower()
        if suf not in _CASE2_SOURCE_EXT:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的源文件类型: {name}（允许 {_CASE2_SOURCE_EXT}）",
            )
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"源文件 {name} 过大")
        validated.append((name, data))
        if suf == ".pdf":
            has_pdf = True
    if not validated:
        raise HTTPException(status_code=400, detail="源文件读取为空，请重新上传")
    return validated, has_pdf

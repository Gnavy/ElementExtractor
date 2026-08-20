import json
import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from docx import Document
from openpyxl import load_workbook
from openpyxl import Workbook
from pptx import Presentation
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import settings
from app.database import get_db
from app.models import Task, TaskStatus
from app.schemas import TaskCreateResponse, TaskListItem, TaskOut
from app.services.paths import (
    ensure_storage,
    task_extract_dir,
)
from app.services.task_create import create_general_task, form_bool
from app.worker_tasks import process_review_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_TEXT_PREVIEW_BYTES = 512 * 1024
MAX_XLSX_PREVIEW_ROWS = 200
MAX_XLSX_PREVIEW_COLUMNS = 50
MAX_DOCX_PREVIEW_BLOCKS = 500
MAX_PPTX_PREVIEW_SLIDES = 100
_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".csv",
        ".xml",
        ".log",
        ".yaml",
        ".yml",
        ".htm",
        ".html",
        ".css",
        ".js",
        ".ts",
    }
)
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"})
_COLLECTION_EXT = frozenset({".xlsx", ".xlsm"})
_TASK_FILE_HIDDEN_NAMES = frozenset({".task-meta.json", ".DS_Store"})
_TASK_FILE_PROCESS_DIRS = frozenset(
    {
        ".claude",
        "tools",
        "ocr_text",
        "__pycache__",
        "case2_fill_batches",
        "image_crops",
    }
)
# outputs 下属于中间产物的目录，不作为成果展示
_TASK_OUTPUT_PROCESS_DIRS = frozenset(
    {
        "case2_fill_batches",
        "__pycache__",
        "image_pdf",
    }
)
_TASK_OUTPUT_PROCESS_NAMES = frozenset(
    {
        "agent.log",
        "claude.log",
        "ocr.log",
        "image_ocr.log",
        "langgraph_checkpoints.sqlite",
        "docx_text_index.json",
        "docx_comments_index.json",
        "ppt_text_index.json",
        "excel_text_index.json",
        "ocr_all_md_index.txt",
        "ocr_litigation_index.txt",
        "field_query_terms.json",
        "tavily_policy_chengdu.json",
        "tavily_policy_chengdu.md",
    }
)


def _form_bool(v: str) -> bool:
    """表单勾选：true/1/on 等为真，其余为假。"""
    return form_bool(v)


def _content_disposition_filename(kind: str, filename: str) -> str:
    """RFC 5987 filename* + ASCII fallback；响应头须为 latin-1 可编码。"""
    pct = quote(filename, safe="")
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = "".join(c if c not in '\\"' else "_" for c in ascii_fallback).strip(
        "._"
    )
    if not ascii_fallback:
        ascii_fallback = "file" + Path(filename).suffix
    return f'{kind}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{pct}'


def _normalize_path_key(path: str) -> str:
    """Collapse LLM-introduced spacing noise for fuzzy path matching."""
    s = path.replace("\\", "/").strip().lstrip("/")
    # 项目 1 → 项目1；9 亿 → 9亿
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=\d)", "", s)
    s = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fff])", "", s)
    # A 浙江 → A浙江；21 .pdf 类
    s = re.sub(r"(?<=[A-Za-z])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", s)
    # 基础资料 - 义乌 → 基础资料-义乌
    s = re.sub(r"\s*-\s*", "-", s)
    # 其它多余空白
    s = re.sub(r"\s+", "", s)
    return s.lower()


def _resolve_extract_file(base: Path, rel: str) -> Path | None:
    """Resolve relative path under extract root; fuzzy-match if exact miss."""
    rel = rel.strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    if target.is_file():
        return target

    # Exact miss: try spacing-normalized match against all files under extract
    want = _normalize_path_key(rel)
    if not want:
        return None
    best: Path | None = None
    best_score = -1
    # Prefer matching full relative path; also allow basename-only as last resort
    for root_name in ("sources", "supplements", "inputs", "ocr_text", "outputs", ""):
        root = base / root_name if root_name else base
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                cand_rel = p.relative_to(base).as_posix()
            except ValueError:
                continue
            key = _normalize_path_key(cand_rel)
            if key == want:
                return p
            # basename match when path prefix drifted
            if key.endswith("/" + want) or key.rsplit("/", 1)[-1] == want.rsplit("/", 1)[-1]:
                # score by common prefix length of normalized strings
                score = 0
                for a, b in zip(key, want):
                    if a == b:
                        score += 1
                    else:
                        break
                if score > best_score and want.rsplit("/", 1)[-1] == key.rsplit("/", 1)[-1]:
                    best_score = score
                    best = p
    return best


def _safe_task_file(task_id: str, path: str, db: Session) -> Tuple[Task, Path]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    rel = path.strip().lstrip("/")
    if ".." in rel or rel.startswith("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    target = _resolve_extract_file(base, rel)
    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return task, target


def _task_file_item(base: Path, target: Path, source: str) -> dict:
    relative_path = target.relative_to(base).as_posix()
    return {
        "name": target.name,
        "relative_path": relative_path,
        "source": source,
        "size": target.stat().st_size,
        "extension": target.suffix.lower(),
    }


def _task_visible_files(task: Task, base: Path) -> list[dict]:
    files: dict[str, dict] = {}

    def add_file(target: Path, source: str) -> None:
        if not target.is_file() or target.name in _TASK_FILE_HIDDEN_NAMES:
            return
        if source == "output" and target.name in _TASK_OUTPUT_PROCESS_NAMES:
            return
        item = _task_file_item(base, target, source)
        files[item["relative_path"]] = item

    for root_name in ("sources", "supplements", "inputs"):
        root = base / root_name
        if root.is_dir():
            for target in sorted(root.rglob("*")):
                if target.is_file():
                    if root_name == "inputs" and not target.name.startswith(
                        "collection_template."
                    ):
                        continue
                    add_file(target, "uploaded")

    for target in sorted(base.iterdir()) if base.is_dir() else []:
        if target.is_file():
            add_file(target, "uploaded")
        elif (
            target.is_dir()
            and target.name not in _TASK_FILE_PROCESS_DIRS
            and target.name not in {"sources", "supplements", "inputs", "outputs"}
        ):
            for child in sorted(target.rglob("*")):
                if child.is_file() and not any(
                    part in _TASK_FILE_PROCESS_DIRS for part in child.relative_to(base).parts
                ):
                    add_file(child, "uploaded")

    outputs = (task.result_summary or {}).get("outputs") or {}
    for relative_path in outputs.values():
        if not isinstance(relative_path, str):
            continue
        target = (base / relative_path).resolve()
        if str(target).startswith(str(base)) and target.is_file():
            add_file(target, "output")

    output_root = base / "outputs"
    if output_root.is_dir():
        for target in sorted(output_root.rglob("*")):
            if not target.is_file():
                continue
            relative_parts = target.relative_to(output_root).parts
            if any(part in _TASK_OUTPUT_PROCESS_DIRS for part in relative_parts):
                continue
            if target.name.startswith("tavily_"):
                continue
            add_file(target, "output")

    return sorted(
        files.values(),
        key=lambda item: (
            0 if item["source"] == "uploaded" else 1,
            item["relative_path"].lower(),
        ),
    )


def _xlsx_cell_value(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _xlsx_preview(target: Path) -> dict:
    try:
        workbook = load_workbook(
            filename=target,
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"无法读取 Excel 文件：{exc}") from exc

    sheets = []
    try:
        for worksheet in workbook.worksheets:
            max_row = min(worksheet.max_row or 0, MAX_XLSX_PREVIEW_ROWS)
            max_column = min(
                worksheet.max_column or 0, MAX_XLSX_PREVIEW_COLUMNS
            )
            rows = [
                [_xlsx_cell_value(cell.value) for cell in row]
                for row in worksheet.iter_rows(
                    min_row=1,
                    max_row=max_row,
                    min_col=1,
                    max_col=max_column,
                )
            ]
            while rows and all(value == "" for value in rows[-1]):
                rows.pop()
            sheets.append(
                {
                    "name": worksheet.title,
                    "rows": rows,
                    "total_rows": worksheet.max_row or 0,
                    "total_columns": worksheet.max_column or 0,
                    "truncated": (worksheet.max_row or 0) > MAX_XLSX_PREVIEW_ROWS
                    or (worksheet.max_column or 0) > MAX_XLSX_PREVIEW_COLUMNS,
                }
            )
    finally:
        workbook.close()

    return {
        "filename": target.name,
        "sheets": sheets,
        "limits": {
            "rows": MAX_XLSX_PREVIEW_ROWS,
            "columns": MAX_XLSX_PREVIEW_COLUMNS,
        },
    }


def _docx_preview(target: Path) -> dict:
    try:
        document = Document(str(target))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"无法读取 Word 文件：{exc}") from exc

    blocks = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style else ""
        blocks.append(
            {
                "type": "paragraph",
                "text": text,
                "style": style_name,
            }
        )
        if len(blocks) >= MAX_DOCX_PREVIEW_BLOCKS:
            break

    if len(blocks) < MAX_DOCX_PREVIEW_BLOCKS:
        for table in document.tables:
            rows = [
                [cell.text.strip() for cell in row.cells]
                for row in table.rows[:100]
            ]
            blocks.append({"type": "table", "rows": rows})
            if len(blocks) >= MAX_DOCX_PREVIEW_BLOCKS:
                break

    return {
        "filename": target.name,
        "blocks": blocks,
        "paragraph_count": len(document.paragraphs),
        "table_count": len(document.tables),
        "truncated": len(blocks) >= MAX_DOCX_PREVIEW_BLOCKS,
    }


def _pptx_preview(target: Path) -> dict:
    try:
        presentation = Presentation(str(target))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"无法读取 PowerPoint 文件：{exc}") from exc

    slides = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        if slide_number > MAX_PPTX_PREVIEW_SLIDES:
            break
        items = []
        title = ""
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            text = "\n".join(
                paragraph.text.strip()
                for paragraph in shape.text_frame.paragraphs
                if paragraph.text.strip()
            )
            if not text:
                continue
            if shape == slide.shapes.title:
                title = text
            else:
                items.append(text)
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        slides.append(
            {
                "number": slide_number,
                "title": title or f"第 {slide_number} 页",
                "items": items,
                "notes": notes,
            }
        )

    return {
        "filename": target.name,
        "slides": slides,
        "slide_count": len(presentation.slides),
        "truncated": len(presentation.slides) > MAX_PPTX_PREVIEW_SLIDES,
    }


def _task_out(task: Task) -> TaskOut:
    return TaskOut.model_validate(task, from_attributes=True)


def _read_json_artifact(base: Path, rel: str) -> dict:
    path = base / rel
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在或尚未生成")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"JSON 解析失败: {exc}") from exc


def _safe_zip_folder_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
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


def _compact_extract_rows(data: dict) -> list[dict]:
    rows = []
    for name, field in (data.get("fields") or {}).items():
        value = field.get("value") if isinstance(field, dict) else field
        rows.append({"name": str(name), "value": value})
    return rows


def _compact_cell_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@router.get("", response_model=list[TaskListItem])
def list_tasks(
    skip: int = 0,
    limit: int = 100,
    task_kind: Optional[Literal["general", "classification", "extraction", "case1", "case2"]] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    if task_kind == "general":
        stmt = stmt.where(
            or_(Task.task_kind == "general", Task.task_kind.is_(None))
        )
    elif task_kind == "classification":
        stmt = stmt.where(Task.task_kind == "classification")
    elif task_kind == "extraction":
        stmt = stmt.where(Task.task_kind == "extraction")
    elif task_kind == "case1":
        stmt = stmt.where(Task.task_kind == "case1")
    elif task_kind == "case2":
        stmt = stmt.where(Task.task_kind == "case2")
    rows = db.scalars(stmt).all()
    return [TaskListItem.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=TaskCreateResponse)
async def create_task(
    files: Optional[list[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    classification_basis: str = Form(...),
    extract_schema: str = Form(...),
    collection_template: Optional[UploadFile] = File(None),
    run_ocr: str = Form("true"),
    run_agent: str = Form("true"),
    run_collection_fill: str = Form("true"),
    db: Session = Depends(get_db),
):
    upload_files = [f for f in (files or []) if f.filename]
    if file is not None and file.filename:
        upload_files.append(file)
    if not upload_files:
        raise HTTPException(status_code=400, detail="请上传至少一个材料文件")

    max_bytes = settings.max_zip_mb * 1024 * 1024
    upload_pairs: list[tuple[str, bytes]] = []
    total_bytes = 0
    for upload in upload_files:
        assert upload.filename is not None
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"上传材料总大小超过 {settings.max_zip_mb} MB 限制",
            )
        upload_pairs.append((upload.filename, content))

    collection_template_bytes: Optional[tuple[str, bytes]] = None
    if collection_template is not None and collection_template.filename:
        cfn = collection_template.filename
        cbytes = await collection_template.read()
        collection_template_bytes = (cfn, cbytes)

    task = create_general_task(
        db,
        upload_pairs=upload_pairs,
        classification_basis=classification_basis,
        extract_schema=extract_schema,
        collection_template_bytes=collection_template_bytes,
        run_ocr=_form_bool(run_ocr),
        run_agent=_form_bool(run_agent),
        run_collection_fill=_form_bool(run_collection_fill),
    )
    return TaskCreateResponse(id=task.id, status=task.status, task_type="general")  # type: ignore[arg-type]


@router.get("/{task_id}/artifacts/classification")
def get_classification_artifact(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    data = _read_json_artifact(base, "outputs/classification.json")
    return JSONResponse(content=data)


@router.get("/{task_id}/artifacts/extracted")
def get_extracted_artifact(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    data = _read_json_artifact(base, "outputs/extracted.json")
    return JSONResponse(content=data)


@router.get("/{task_id}/extracted-export")
def export_extracted_data(
    task_id: str,
    format: Literal["json", "xlsx"] = "json",
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    data = _read_json_artifact(base, "outputs/extracted.json")
    rows = _compact_extract_rows(data)
    base_name = f"{Path(task.zip_filename).stem}_抽取结果"

    if format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"{base_name}.json"
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": _content_disposition_filename(
                    "attachment", filename
                )
            },
        )

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "抽取结果"
    worksheet.append(["名称", "值"])
    worksheet.freeze_panes = "A2"
    worksheet.column_dimensions["A"].width = 32
    worksheet.column_dimensions["B"].width = 80
    for row in rows:
        worksheet.append([row["name"], _compact_cell_value(row["value"])])
    temp = tempfile.NamedTemporaryFile(
        prefix=f"extracted_{task_id}_", suffix=".xlsx", delete=False
    )
    temp_path = Path(temp.name)
    temp.close()
    workbook.save(temp_path)
    filename = f"{base_name}.xlsx"
    return FileResponse(
        path=str(temp_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(temp_path.unlink, missing_ok=True),
        headers={
            "Content-Disposition": _content_disposition_filename(
                "attachment", filename
            )
        },
    )


@router.get("/{task_id}/files")
def list_task_files(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    if not base.is_dir():
        return JSONResponse(content={"files": []})
    return JSONResponse(content={"files": _task_visible_files(task, base)})


@router.get("/{task_id}/classification-package")
def download_classification_package(
    task_id: str, db: Session = Depends(get_db)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    base = task_extract_dir(task_id).resolve()
    classification = _read_json_artifact(base, "outputs/classification.json")
    used_paths: set[str] = set()
    temp = tempfile.NamedTemporaryFile(
        prefix=f"classification_{task_id}_", suffix=".zip", delete=False
    )
    temp_path = Path(temp.name)
    temp.close()

    try:
        with zipfile.ZipFile(
            temp_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for category_index, category in enumerate(
                classification.get("categories") or [], start=1
            ):
                folder = _safe_zip_folder_name(
                    str(category.get("label") or ""),
                    f"分类_{category_index}",
                )
                for file_item in category.get("files") or []:
                    relative_path = str(file_item.get("relative_path") or "")
                    try:
                        _, target = _safe_task_file(
                            task_id, relative_path, db
                        )
                    except HTTPException:
                        continue
                    archive_name = _unique_zip_path(
                        f"{folder}/{target.name}", used_paths
                    )
                    archive.write(target, archive_name)

            unclassified = classification.get("unclassified") or []
            for file_item in unclassified:
                relative_path = str(file_item.get("relative_path") or "")
                try:
                    _, target = _safe_task_file(task_id, relative_path, db)
                except HTTPException:
                    continue
                archive_name = _unique_zip_path(
                    f"未分类/{target.name}", used_paths
                )
                archive.write(target, archive_name)

        if not used_paths:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="没有可打包的分类文件")

        filename = f"{Path(task.zip_filename).stem}_分类材料.zip"
        return FileResponse(
            path=str(temp_path),
            media_type="application/zip",
            filename=filename,
            background=BackgroundTask(temp_path.unlink, missing_ok=True),
            headers={
                "Content-Disposition": _content_disposition_filename(
                    "attachment", filename
                )
            },
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


@router.get("/{task_id}/download")
def download_task_file(task_id: str, path: str, db: Session = Depends(get_db)):
    _, target = _safe_task_file(task_id, path, db)
    return FileResponse(
        path=str(target),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition_filename(
                "attachment", target.name
            ),
        },
    )


@router.get("/{task_id}/preview")
def preview_task_file(task_id: str, path: str, db: Session = Depends(get_db)):
    """在线预览：文本、PDF、图片与 Excel；其他 Office 格式返回 415。"""
    _, target = _safe_task_file(task_id, path, db)
    suffix = target.suffix.lower()

    if suffix == ".pdf":
        disp = _content_disposition_filename("inline", target.name)
        return FileResponse(
            path=str(target),
            media_type="application/pdf",
            headers={"Content-Disposition": disp},
        )

    if suffix in _IMAGE_SUFFIXES:
        mt = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".bmp": "image/bmp",
        }.get(suffix, "application/octet-stream")
        disp = _content_disposition_filename("inline", target.name)
        return FileResponse(
            path=str(target),
            media_type=mt,
            headers={"Content-Disposition": disp},
        )

    if suffix in _TEXT_SUFFIXES:
        raw_full = target.read_bytes()
        truncated = len(raw_full) > MAX_TEXT_PREVIEW_BYTES
        raw = raw_full[:MAX_TEXT_PREVIEW_BYTES] if truncated else raw_full
        text = raw.decode("utf-8", errors="replace")
        if truncated:
            text += "\n\n… (内容过长已截断)"
        return Response(
            content=text.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"X-Preview-Truncated": "true" if truncated else "false"},
        )

    if suffix in _COLLECTION_EXT:
        return JSONResponse(content=_xlsx_preview(target))

    if suffix == ".docx":
        return JSONResponse(content=_docx_preview(target))

    if suffix == ".pptx":
        return JSONResponse(content=_pptx_preview(target))

    raise HTTPException(
        status_code=415,
        detail="当前类型不支持浏览器内预览，请使用下载",
    )


@router.post("/{task_id}/resume", response_model=TaskCreateResponse)
def resume_task(task_id: str, db: Session = Depends(get_db)):
    """失败任务续跑：保留已有解压目录与中间产物，重新入队。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"仅失败任务可续跑，当前状态：{task.status}",
        )
    zip_path = Path(task.zip_path) if task.zip_path else None
    if not zip_path or not zip_path.is_file():
        raise HTTPException(status_code=400, detail="原始上传文件已丢失，无法续跑")

    task.status = TaskStatus.PENDING.value
    task.error_message = None
    task.progress_message = "续跑已排队"
    db.commit()

    process_review_task.apply_async(args=[task_id], kwargs={"resume": True})
    return TaskCreateResponse(id=task.id, status=task.status)  # type: ignore[arg-type]


_ACTIVE_STATUSES = frozenset(
    {
        TaskStatus.PENDING.value,
        TaskStatus.EXTRACTING.value,
        TaskStatus.OCR_RUNNING.value,
        TaskStatus.AGENT_RUNNING.value,
    }
)


@router.post("/{task_id}/rerun", response_model=TaskCreateResponse)
def rerun_task(task_id: str, db: Session = Depends(get_db)):
    """从头重跑：清空解压目录与 outputs，重新执行完整流水线。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"任务进行中，请稍后再试（当前状态：{task.status}）",
        )
    zip_path = Path(task.zip_path) if task.zip_path else None
    if not zip_path or not zip_path.is_file():
        raise HTTPException(status_code=400, detail="原始上传文件已丢失，无法重跑")

    extract_root = task_extract_dir(task_id)
    if extract_root.exists():
        shutil.rmtree(extract_root)

    task.status = TaskStatus.PENDING.value
    task.error_message = None
    task.progress_message = "重跑已排队"
    task.result_summary = None
    task.claude_log_tail = None
    db.commit()

    process_review_task.apply_async(args=[task_id], kwargs={"resume": False})
    return TaskCreateResponse(id=task.id, status=task.status)  # type: ignore[arg-type]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_out(task)


@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
    }:
        raise HTTPException(status_code=409, detail="处理中任务不能删除")

    extract_root = task_extract_dir(task_id).resolve()
    if extract_root.is_dir():
        shutil.rmtree(extract_root)

    ensure_storage()
    for upload_file in settings.uploads_dir.glob(f"{task_id}_*"):
        if upload_file.is_file():
            upload_file.unlink()
        elif upload_file.is_dir():
            shutil.rmtree(upload_file)

    db.delete(task)
    db.commit()
    return {"ok": True, "id": task_id}

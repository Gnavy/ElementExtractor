from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.tasks import (
    download_task_file,
    get_classification_artifact,
    get_extracted_artifact,
    get_task,
    list_task_files,
    list_tasks,
    resume_task,
    rerun_task,
)
from app.database import get_db
from app.deps.auth import verify_api_key
from app.schemas import (
    ErrorResponse,
    TaskCreateResponse,
    TaskListItem,
    TaskListItemV1,
    TaskOutV1,
    TaskType,
)
from app.services.task_create import (
    create_case1_task,
    create_case2_task,
    create_classification_task,
    create_extraction_task,
    form_bool,
    validate_case1_supplements,
    validate_case2_sources,
)
from app.services.task_types import (
    EXTERNAL_TASK_TYPE_LABELS,
    to_external_task_type,
    to_internal_task_kind,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["v1-tasks"],
    dependencies=[Depends(verify_api_key)],
)

_UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "API Key 无效或缺失"}}
_SERVICE_UNAVAILABLE = {503: {"model": ErrorResponse, "description": "服务端未配置 API_KEYS"}}
_COMMON_ERRORS = {
    **_UNAUTHORIZED,
    **_SERVICE_UNAVAILABLE,
    400: {"model": ErrorResponse, "description": "请求参数错误"},
    404: {"model": ErrorResponse, "description": "资源不存在"},
}

_TASK_TYPE_DOC = (
    "任务类型：`classification`（材料分类）、`extraction`（要素抽取）、"
    "`due_diligence`（债权尽调指标填报）、`template_fill`（模板驱动填报）"
)


async def _read_upload_pairs(
    upload_files: list[UploadFile],
) -> list[tuple[str, bytes]]:
    from app.config import settings

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
    return upload_pairs


def _to_list_item_v1(item: TaskListItem) -> TaskListItemV1:
    return TaskListItemV1(
        id=item.id,
        status=item.status,
        zip_filename=item.zip_filename,
        task_type=to_external_task_type(item.task_kind),
        source_docx_filename=item.source_docx_filename,
        progress_message=item.progress_message,
        error_message=item.error_message,
        created_at=item.created_at,
    )


def _create_response(task_id: str, status: str, task_kind: str) -> TaskCreateResponse:
    return TaskCreateResponse(
        id=task_id,
        status=status,
        task_type=to_external_task_type(task_kind),
    )


@router.get(
    "/tasks",
    response_model=list[TaskListItemV1],
    summary="任务列表",
    description=f"按创建时间倒序返回任务；可用 `task_type` 过滤。{_TASK_TYPE_DOC}",
    responses=_COMMON_ERRORS,
)
def v1_list_tasks(
    skip: int = 0,
    limit: int = 100,
    task_type: Optional[TaskType] = None,
    db: Session = Depends(get_db),
):
    internal_kind = to_internal_task_kind(task_type.value) if task_type else None
    rows = list_tasks(skip=skip, limit=limit, task_kind=internal_kind, db=db)
    return [_to_list_item_v1(item) for item in rows]


@router.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=201,
    summary="统一创建任务",
    description=(
        f"通过 `task_type` 选择任务类型并上传对应材料。{_TASK_TYPE_DOC} "
        "`classification` 需 `files`、`classification_basis`；"
        "`extraction` 需 `files`、`extract_schema`；"
        "`due_diligence` 需 `due_diligence_docx`；"
        "`template_fill` 需 `source_files` 与 `collection_template`。"
    ),
    responses=_COMMON_ERRORS,
)
async def v1_create_task(
    task_type: TaskType = Form(..., description=_TASK_TYPE_DOC),
    files: Optional[List[UploadFile]] = File(
        None, description="classification / extraction：材料文件（可多选）"
    ),
    classification_basis: str = Form("", description="classification：分类依据"),
    extract_schema: str = Form("", description="extraction：抽取 schema（JSON 字符串）"),
    collection_template: Optional[UploadFile] = File(
        None, description="template_fill：填报模板 xlsx"
    ),
    run_ocr: str = Form("true"),
    due_diligence_docx: Optional[UploadFile] = File(
        None, description="due_diligence：尽调 docx"
    ),
    supplementary_files: Optional[List[UploadFile]] = File(
        None, description="due_diligence：补充材料"
    ),
    indicator_judgment_rules: str = Form("", description="due_diligence：指标判断规则"),
    source_files: Optional[List[UploadFile]] = File(None, description="template_fill：源文件"),
    fill_logic_rules: str = Form("", description="template_fill：填表逻辑与计算规则"),
    db: Session = Depends(get_db),
):
    if task_type == TaskType.classification:
        upload_files = [f for f in (files or []) if f.filename]
        if not upload_files:
            raise HTTPException(status_code=400, detail="classification 任务须上传至少一个 files")
        if not classification_basis.strip():
            raise HTTPException(
                status_code=400, detail="classification 任务须提供 classification_basis"
            )
        upload_pairs = await _read_upload_pairs(upload_files)
        task = create_classification_task(
            db,
            upload_pairs=upload_pairs,
            classification_basis=classification_basis,
            run_ocr=form_bool(run_ocr),
        )
        return _create_response(task.id, task.status, task.task_kind)

    if task_type == TaskType.extraction:
        upload_files = [f for f in (files or []) if f.filename]
        if not upload_files:
            raise HTTPException(status_code=400, detail="extraction 任务须上传至少一个 files")
        if not extract_schema.strip():
            raise HTTPException(status_code=400, detail="extraction 任务须提供 extract_schema")
        upload_pairs = await _read_upload_pairs(upload_files)
        task = create_extraction_task(
            db,
            upload_pairs=upload_pairs,
            extract_schema=extract_schema,
            classification_basis=classification_basis,
            run_ocr=form_bool(run_ocr),
        )
        return _create_response(task.id, task.status, task.task_kind)

    if task_type == TaskType.due_diligence:
        if due_diligence_docx is None or not due_diligence_docx.filename:
            raise HTTPException(
                status_code=400,
                detail="due_diligence 任务须上传 due_diligence_docx",
            )
        docx_name = Path(due_diligence_docx.filename).name
        docx_bytes = await due_diligence_docx.read()

        raw_supplements: list[tuple[str, bytes]] = []
        for uf in supplementary_files or []:
            if not uf.filename:
                continue
            raw_supplements.append((Path(uf.filename).name, await uf.read()))
        supplements, needs_ocr = validate_case1_supplements(raw_supplements)

        task = create_case1_task(
            db,
            docx_name=docx_name,
            docx_bytes=docx_bytes,
            supplements=supplements,
            run_ocr=form_bool(run_ocr) or needs_ocr,
            indicator_judgment_rules=indicator_judgment_rules,
        )
        return _create_response(task.id, task.status, task.task_kind)

    if task_type == TaskType.template_fill:
        raw_sources: list[tuple[str, bytes]] = []
        for uf in source_files or []:
            if not uf.filename:
                continue
            raw_sources.append((Path(uf.filename).name, await uf.read()))
        src_pairs, has_pdf = validate_case2_sources(raw_sources)

        if collection_template is None or not collection_template.filename:
            raise HTTPException(
                status_code=400,
                detail="template_fill 任务须上传 collection_template",
            )
        tpl_name = Path(collection_template.filename).name
        tpl_bytes = await collection_template.read()

        task = create_case2_task(
            db,
            src_pairs=src_pairs,
            template_name=tpl_name,
            template_bytes=tpl_bytes,
            run_ocr=form_bool(run_ocr) or has_pdf,
            fill_logic_rules=fill_logic_rules,
        )
        return _create_response(task.id, task.status, task.task_kind)

    label = EXTERNAL_TASK_TYPE_LABELS.get(task_type.value, task_type.value)
    raise HTTPException(status_code=400, detail=f"不支持的 task_type: {label}")


@router.get(
    "/tasks/{task_id}",
    response_model=TaskOutV1,
    summary="任务详情",
    description="轮询任务状态直至 `COMPLETED` 或 `FAILED`。",
    responses=_COMMON_ERRORS,
)
def v1_get_task(task_id: str, db: Session = Depends(get_db)):
    return TaskOutV1.from_task_out(get_task(task_id=task_id, db=db))


@router.get(
    "/tasks/{task_id}/files",
    summary="任务文件列表",
    responses=_COMMON_ERRORS,
)
def v1_list_task_files(task_id: str, db: Session = Depends(get_db)):
    return list_task_files(task_id=task_id, db=db)


@router.get(
    "/tasks/{task_id}/download",
    summary="下载任务产物",
    description="`path` 为相对任务目录的路径，如 `outputs/collection_filled.xlsx`。",
    responses=_COMMON_ERRORS,
)
def v1_download_task_file(task_id: str, path: str, db: Session = Depends(get_db)):
    return download_task_file(task_id=task_id, path=path, db=db)


@router.post(
    "/tasks/{task_id}/resume",
    response_model=TaskCreateResponse,
    summary="失败任务续跑",
    responses=_COMMON_ERRORS,
)
def v1_resume_task(task_id: str, db: Session = Depends(get_db)):
    resp = resume_task(task_id=task_id, db=db)
    task = get_task(task_id=task_id, db=db)
    return _create_response(resp.id, resp.status, task.task_kind)


@router.post(
    "/tasks/{task_id}/rerun",
    response_model=TaskCreateResponse,
    summary="任务重跑",
    responses=_COMMON_ERRORS,
)
def v1_rerun_task(task_id: str, db: Session = Depends(get_db)):
    resp = rerun_task(task_id=task_id, db=db)
    task = get_task(task_id=task_id, db=db)
    return _create_response(resp.id, resp.status, task.task_kind)


@router.get(
    "/tasks/{task_id}/artifacts/classification",
    summary="classification：分类结果 JSON",
    responses=_COMMON_ERRORS,
)
def v1_get_classification_artifact(task_id: str, db: Session = Depends(get_db)):
    return get_classification_artifact(task_id=task_id, db=db)


@router.get(
    "/tasks/{task_id}/artifacts/extracted",
    summary="extraction：要素抽取 JSON",
    responses=_COMMON_ERRORS,
)
def v1_get_extracted_artifact(task_id: str, db: Session = Depends(get_db)):
    return get_extracted_artifact(task_id=task_id, db=db)

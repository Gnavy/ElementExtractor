from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TaskCreateResponse
from app.services.task_create import create_case1_task, form_bool, validate_case1_supplements

router = APIRouter(prefix="/api/case1", tags=["case1"])


@router.post("/tasks", response_model=TaskCreateResponse)
async def create_case1_task_endpoint(
    due_diligence_docx: UploadFile = File(...),
    supplementary_files: Optional[List[UploadFile]] = File(None),
    run_ocr: str = Form("true"),
    indicator_judgment_rules: str = Form(""),
    db: Session = Depends(get_db),
):
    if not due_diligence_docx.filename:
        raise HTTPException(status_code=400, detail="请上传尽职调查 .docx 文件")
    docx_name = Path(due_diligence_docx.filename).name
    docx_bytes = await due_diligence_docx.read()

    raw_supplements: list[tuple[str, bytes]] = []
    for uf in supplementary_files or []:
        if not uf.filename:
            continue
        name = Path(uf.filename).name
        raw_supplements.append((name, await uf.read()))

    supplements, needs_ocr = validate_case1_supplements(raw_supplements)
    run_ocr_flag = form_bool(run_ocr) or needs_ocr

    task = create_case1_task(
        db,
        docx_name=docx_name,
        docx_bytes=docx_bytes,
        supplements=supplements,
        run_ocr=run_ocr_flag,
        indicator_judgment_rules=indicator_judgment_rules,
    )
    return TaskCreateResponse(id=task.id, status=task.status, task_type="case1")  # type: ignore[arg-type]

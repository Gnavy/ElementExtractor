from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TaskCreateResponse
from app.services.task_create import create_case2_task, form_bool, validate_case2_sources

router = APIRouter(prefix="/api/case2", tags=["case2"])


@router.post("/tasks", response_model=TaskCreateResponse)
async def create_case2_task_endpoint(
    source_files: Optional[List[UploadFile]] = File(None),
    collection_template: UploadFile = File(...),
    run_ocr: str = Form("true"),
    fill_logic_rules: str = Form(""),
    db: Session = Depends(get_db),
):
    files = source_files or []
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传 1 个源文件")

    if not collection_template.filename:
        raise HTTPException(status_code=400, detail="请上传模板文件（xlsx）")
    tpl_name = Path(collection_template.filename).name

    raw_pairs: list[tuple[str, bytes]] = []
    for uf in files:
        if not uf.filename:
            continue
        name = Path(uf.filename).name
        raw_pairs.append((name, await uf.read()))

    src_pairs, has_pdf = validate_case2_sources(raw_pairs)
    tpl_bytes = await collection_template.read()
    run_ocr_flag = form_bool(run_ocr) or has_pdf

    task = create_case2_task(
        db,
        src_pairs=src_pairs,
        template_name=tpl_name,
        template_bytes=tpl_bytes,
        run_ocr=run_ocr_flag,
        fill_logic_rules=fill_logic_rules,
    )
    return TaskCreateResponse(id=task.id, status=task.status, task_type="case2")  # type: ignore[arg-type]

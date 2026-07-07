import enum
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.services.task_types import to_external_task_type


class TaskType(str, enum.Enum):
    """对外 API `/api/v1` 的 task_type 取值。"""

    classification = "classification"
    extraction = "extraction"
    due_diligence = "due_diligence"
    template_fill = "template_fill"


class TaskCreateResponse(BaseModel):
    id: str
    status: str
    task_type: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str


class TaskOut(BaseModel):
    id: str
    status: str
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    classification_basis: str
    extract_schema: str
    zip_filename: str
    task_kind: str = "general"
    source_docx_filename: Optional[str] = None
    indicator_judgment_rules: Optional[str] = None
    fill_logic_rules: Optional[str] = None
    collection_template_original_filename: Optional[str] = None
    run_ocr: bool = True
    run_agent: bool = True
    run_collection_fill: bool = True
    result_summary: Optional[Dict[str, Any]] = None
    claude_log_tail: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskListItem(BaseModel):
    id: str
    status: str
    zip_filename: str
    task_kind: str = "general"
    source_docx_filename: Optional[str] = None
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskListItemV1(BaseModel):
    id: str
    status: str
    zip_filename: str
    task_type: str
    source_docx_filename: Optional[str] = None
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class TaskOutV1(BaseModel):
    id: str
    status: str
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    classification_basis: str
    extract_schema: str
    zip_filename: str
    task_type: str
    source_docx_filename: Optional[str] = None
    indicator_judgment_rules: Optional[str] = None
    fill_logic_rules: Optional[str] = None
    collection_template_original_filename: Optional[str] = None
    run_ocr: bool = True
    run_agent: bool = True
    run_collection_fill: bool = True
    result_summary: Optional[Dict[str, Any]] = None
    claude_log_tail: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_task_out(cls, task: TaskOut) -> "TaskOutV1":
        data = task.model_dump()
        data["task_type"] = to_external_task_type(data.pop("task_kind", "general"))
        return cls.model_validate(data)


class ExtractFieldItem(BaseModel):
    name: str
    description: str = ""
    type: Optional[str] = Field(
        default=None,
        description="可选：string|text|number|currency|date|boolean|array|object|image 等",
    )


class ExtractSchemaInput(BaseModel):
    """Optional helper schema when client sends JSON body instead of form."""

    fields: list[ExtractFieldItem] = Field(default_factory=list)

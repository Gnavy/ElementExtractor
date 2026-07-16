from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class FileRef(BaseModel):
    relative_path: str
    file_type: str = "other"
    notes: Optional[str] = None


class CategoryItem(BaseModel):
    label: str
    files: list[FileRef] = Field(default_factory=list)


class UnclassifiedItem(BaseModel):
    relative_path: str
    reason: str = ""


class ClassificationResult(BaseModel):
    task_id: str = ""
    categories: list[CategoryItem] = Field(default_factory=list)
    unclassified: list[UnclassifiedItem] = Field(default_factory=list)

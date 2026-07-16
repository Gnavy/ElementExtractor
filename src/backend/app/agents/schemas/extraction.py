from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    file: str = ""
    quote: str = ""
    page_hint: Optional[str] = None


class ExtractedField(BaseModel):
    value: Any = None
    confidence: str = Field(default="medium", description="high|medium|low")
    source_files: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: Optional[str] = None


class FieldExtractResult(BaseModel):
    """Structured output when extracting a single schema field."""

    field_name: str
    value: Any = None
    confidence: str = "medium"
    source_files: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: Optional[str] = None
    # Optional crop hint for image fields
    crop_bbox: Optional[str] = Field(
        default=None,
        description="x,y,width,height pixels if type=image",
    )
    crop_page: Optional[int] = None
    crop_source: Optional[str] = None


class ExtractionResult(BaseModel):
    task_id: str = ""
    fields: dict[str, ExtractedField] = Field(default_factory=dict)


class GradeEvidence(BaseModel):
    """Binary groundedness check for a field extraction."""

    grounded: bool = Field(description="True if value is supported by evidence quotes")
    reason: str = ""


class FieldQueryTerms(BaseModel):
    """检索词扩展：用于 OCR 文件重排，不直接当抽取答案。"""

    field_name: str = Field(description="必须与输入字段名完全一致")
    query_terms: list[str] = Field(
        default_factory=list,
        description="同义词/材料常见说法/证照类型等检索词，约 8-15 个",
    )
    doc_hints: list[str] = Field(
        default_factory=list,
        description="更可能出现的文件名或目录线索，可空",
    )


class QueryExpansionResult(BaseModel):
    fields: list[FieldQueryTerms] = Field(default_factory=list)


class CollectionCellFill(BaseModel):
    sheet: str
    row: int
    col: Union[int, str]
    value: str
    remark: Optional[str] = None


class CollectionFillPlan(BaseModel):
    cells: list[CollectionCellFill] = Field(default_factory=list)
    gap_notes: list[str] = Field(default_factory=list)

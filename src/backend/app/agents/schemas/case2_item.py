from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Case2FieldValue(BaseModel):
    cell: str = ""
    value: Any = None


class Case2ItemFill(BaseModel):
    item_id: str
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="key = column letter or choice/remark; value = filled value",
    )
    confidence: Optional[str] = "medium"
    reason_one_line: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)


class Case2BatchFill(BaseModel):
    items: list[Case2ItemFill] = Field(default_factory=list)

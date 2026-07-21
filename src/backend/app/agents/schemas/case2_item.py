from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.agents.schemas.coerce import coerce_json_dict, coerce_json_list


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

    @field_validator("fields", mode="before")
    @classmethod
    def _coerce_fields(cls, v):
        return coerce_json_dict(v)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, v):
        return coerce_json_list(v)


class Case2BatchFill(BaseModel):
    items: list[Case2ItemFill] = Field(
        default_factory=list,
        description="批量填报结果，必须是对象数组，禁止字符串化",
    )

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, v):
        return coerce_json_list(v)

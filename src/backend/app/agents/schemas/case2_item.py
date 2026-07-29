from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.agents.schemas.coerce import coerce_json_dict, coerce_json_list


Case2Scalar = str | int | float | bool | None


def _coerce_object_list(value):
    """兼容模型把单条对象直接返回给数组字段。"""
    parsed = coerce_json_list(value)
    return [parsed] if isinstance(parsed, dict) else parsed


def _coerce_period_hint_list(value):
    parsed = _coerce_object_list(value)
    if not isinstance(parsed, list):
        return parsed
    structured = [
        item for item in parsed if isinstance(item, (dict, Case2PeriodHint))
    ]
    if structured:
        return structured

    labels = {
        "企业主体": "entity_name",
        "报表口径": "statement_scope",
        "报表名称": "statement_name",
        "报告日期": "report_date",
        "源表列标题": "source_period",
    }
    hint: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, str):
            continue
        label, separator, content = item.partition(":")
        if not separator:
            label, separator, content = item.partition("：")
        key = labels.get(label.strip())
        if key and content.strip():
            hint[key] = content.strip()
    return [hint] if hint else []


class Case2ItemFill(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str
    fields: dict[str, Case2Scalar] = Field(
        default_factory=dict,
        description="key = column letter or choice/remark; value = filled value",
    )
    confidence: Literal["high", "medium", "low"] = "low"
    reason_one_line: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("fields", mode="before")
    @classmethod
    def _coerce_fields(cls, v):
        parsed = coerce_json_dict(v)
        if not isinstance(parsed, dict):
            return parsed
        return {
            key: value.get("value")
            if isinstance(value, dict) and "value" in value
            else value
            for key, value in parsed.items()
        }

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, v):
        return coerce_json_list(v)


class Case2BatchFill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Case2ItemFill] = Field(
        default_factory=list,
        description="批量填报结果，必须是对象数组，禁止字符串化",
    )

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, v):
        return _coerce_object_list(v)


class Case2ChunkFact(BaseModel):
    """单个 OCR 分块中可直接取证的财务事实。"""

    model_config = ConfigDict(extra="ignore")

    item_id: str
    subject_name: Optional[str] = None
    entity_name: Optional[str] = None
    statement_scope: Optional[Literal["合并", "母公司", "单体", "未知"]] = "未知"
    statement_name: Optional[str] = None
    source_period: str = ""
    report_date: Optional[str] = None
    value: str | int | float | None
    unit: Optional[str] = None
    evidence_text: str
    confidence: Literal["high", "medium", "low"] = "medium"


class Case2PeriodHint(BaseModel):
    """单个分块内识别出的报表名称、日期和列标题线索。"""

    model_config = ConfigDict(extra="forbid")

    entity_name: Optional[str] = None
    statement_scope: Optional[Literal["合并", "母公司", "单体", "未知"]] = "未知"
    statement_name: Optional[str] = None
    report_date: Optional[str] = None
    source_period: Optional[str] = None
    evidence_text: str = ""


class Case2ChunkEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_hints: list[Case2PeriodHint] = Field(default_factory=list)
    facts: list[Case2ChunkFact] = Field(default_factory=list)

    @field_validator("period_hints", mode="before")
    @classmethod
    def _coerce_period_hints(cls, v):
        return _coerce_period_hint_list(v)

    @field_validator("facts", mode="before")
    @classmethod
    def _coerce_facts(cls, v):
        return _coerce_object_list(v)


class Case2ColumnPeriod(BaseModel):
    """模板列与源报表报告期的一次性全局映射。"""

    model_config = ConfigDict(extra="ignore")

    sheet_name: str = ""
    field_key: str = Field(
        validation_alias=AliasChoices("field_key", "template_column")
    )
    column_label: str = ""
    entity_name: Optional[str] = None
    statement_scope: Optional[Literal["合并", "母公司", "单体", "未知"]] = "未知"
    source_period: Optional[str] = None
    report_date: Optional[str] = None
    statement_name: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = "low"
    evidence_text: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("evidence_text", "evidence"),
    )
    source_ref: Optional[str] = None


class Case2PeriodMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[Case2ColumnPeriod] = Field(default_factory=list)

    @field_validator("columns", mode="before")
    @classmethod
    def _coerce_columns(cls, v):
        return _coerce_object_list(v)

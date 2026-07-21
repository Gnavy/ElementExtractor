from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.agents.schemas.coerce import coerce_json_list


class Case1RowFill(BaseModel):
    row: int
    choice: Optional[str] = Field(
        default=None,
        description="D列指标选择：yes_no 填「是」/「否」；exclusive 填选项全文或留空",
    )
    remark: str = Field(
        default="",
        description=(
            "E列备注：判断要点 + <引用>源文件名：原文「……」</引用>；"
            "必须含源文件名与原文摘录，禁止只写见报告"
        ),
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="证据路径列表（JSON 数组，不要序列化成字符串）",
    )

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, v):
        return coerce_json_list(v)


class Case1GroupFill(BaseModel):
    indicator_name: str = ""
    rows: list[Case1RowFill] = Field(
        default_factory=list,
        description="本组各行填报结果，必须是对象数组，禁止把数组再 JSON 字符串化",
    )
    notes: Optional[str] = None

    @field_validator("rows", mode="before")
    @classmethod
    def _coerce_rows(cls, v):
        return coerce_json_list(v)


class RegionResolve(BaseModel):
    city: str = Field(default="", description="项目所在城市")
    district: str = Field(default="", description="区县/板块，可空")
    evidence: str = Field(default="", description="推断依据摘要")

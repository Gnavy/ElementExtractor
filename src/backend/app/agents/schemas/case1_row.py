from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Case1RowFill(BaseModel):
    row: int
    choice: Optional[str] = Field(
        default=None,
        description="D列指标选择：yes_no 填「是」/「否」；exclusive 填选项全文或留空",
    )
    remark: str = Field(
        default="",
        description="E列一句话备注（含关键事实与数据源文件）",
    )
    evidence_refs: list[str] = Field(default_factory=list)


class Case1GroupFill(BaseModel):
    indicator_name: str = ""
    rows: list[Case1RowFill] = Field(default_factory=list)
    notes: Optional[str] = None


class RegionResolve(BaseModel):
    city: str = Field(default="", description="项目所在城市")
    district: str = Field(default="", description="区县/板块，可空")
    evidence: str = Field(default="", description="推断依据摘要")

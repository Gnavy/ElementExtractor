"""对外 API task_type 与内部 task_kind 映射。"""

from typing import Optional

# 对外 task_type（/api/v1）→ 内部 task_kind（数据库 / Worker）
EXTERNAL_TO_INTERNAL: dict[str, str] = {
    "classification": "classification",
    "extraction": "extraction",
    "due_diligence": "case1",
    "template_fill": "case2",
    # 兼容旧取值
    "general": "general",
    "business_review": "general",
    "debt_due_diligence_fill": "case1",
    "template_driven_fill": "case2",
    "case1": "case1",
    "case2": "case2",
}

INTERNAL_TO_EXTERNAL: dict[str, str] = {
    "general": "general",
    "classification": "classification",
    "extraction": "extraction",
    "case1": "due_diligence",
    "case2": "template_fill",
}

EXTERNAL_TASK_TYPE_LABELS: dict[str, str] = {
    "classification": "材料分类",
    "extraction": "要素抽取",
    "due_diligence": "债权尽调指标填报",
    "template_fill": "模板驱动填报",
    "general": "通用业务审查（内部）",
}


def to_internal_task_kind(task_type: str) -> str:
    key = (task_type or "").strip().lower()
    internal = EXTERNAL_TO_INTERNAL.get(key)
    if internal is None:
        raise ValueError(key)
    return internal


def to_external_task_type(task_kind: Optional[str]) -> str:
    kind = (task_kind or "general").strip().lower()
    return INTERNAL_TO_EXTERNAL.get(kind, kind)


def is_valid_external_task_type(task_type: str) -> bool:
    return (task_type or "").strip().lower() in EXTERNAL_TO_INTERNAL

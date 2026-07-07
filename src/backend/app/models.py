import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON

from app.database import Base


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    OCR_RUNNING = "OCR_RUNNING"
    AGENT_RUNNING = "AGENT_RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value)
    progress_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    classification_basis: Mapped[str] = mapped_column(Text)
    extract_schema: Mapped[str] = mapped_column(Text)
    zip_filename: Mapped[str] = mapped_column(String(512))
    zip_md5: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    task_kind: Mapped[str] = mapped_column(String(32), default="general")
    source_docx_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    indicator_judgment_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fill_logic_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    collection_template_original_filename: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )

    run_ocr: Mapped[bool] = mapped_column(Boolean, default=True)
    run_agent: Mapped[bool] = mapped_column(Boolean, default=True)
    run_collection_fill: Mapped[bool] = mapped_column(Boolean, default=True)

    zip_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    extract_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    result_summary: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    claude_log_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

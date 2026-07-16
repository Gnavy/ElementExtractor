"""Progress logging helpers for agent runs."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Optional

from app.config import settings

ProgressCallback = Optional[Callable[[str], None]]


class ProgressLogger:
    """Append log lines and optionally notify Worker (DB progress_message)."""

    def __init__(
        self,
        *,
        task_id: str | None = None,
        on_progress: ProgressCallback = None,
        log_path=None,
    ) -> None:
        self.task_id = task_id
        self.on_progress = on_progress
        self.log_path = log_path
        self.lines: list[str] = []

    def log(self, message: str) -> None:
        msg = message.rstrip()
        self.lines.append(msg)
        prefix = f"[agent task={self.task_id}] " if self.task_id else "[agent] "
        if settings.agent_stream_to_console:
            sys.stdout.write(f"{prefix}{msg}\n")
            sys.stdout.flush()
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as fp:
                fp.write(msg + "\n")
        if self.on_progress is not None:
            try:
                self.on_progress(msg)
            except Exception:  # noqa: BLE001
                pass

    def tail(self, n: int = 6000) -> str:
        text = "\n".join(self.lines)
        return text[-n:] if len(text) > n else text

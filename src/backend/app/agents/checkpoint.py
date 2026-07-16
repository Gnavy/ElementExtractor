"""Per-task SqliteSaver for LangGraph durable execution / resume."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def checkpoint_db_path(extract_root: Path) -> Path:
    outputs = extract_root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    return outputs / "langgraph_checkpoints.sqlite"


@contextmanager
def open_checkpointer(extract_root: Path) -> Iterator[Any]:
    """
    Yield a SqliteSaver bound to the task extract dir.

    If langgraph-checkpoint-sqlite is unavailable, yield None (graphs still run
    without durable checkpoints).
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        yield None
        return

    db = checkpoint_db_path(extract_root)
    try:
        with SqliteSaver.from_conn_string(str(db)) as saver:
            yield saver
    except Exception:
        # 断点库损坏或不兼容时降级为无 checkpointer
        yield None


def thread_config(task_id: str) -> dict:
    return {"configurable": {"thread_id": str(task_id)}}

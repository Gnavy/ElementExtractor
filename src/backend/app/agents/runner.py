"""LangGraph agent runner — drop-in replacement for run_claude()."""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from app.agents.checkpoint import open_checkpointer, thread_config
from app.agents.graphs.case1 import build_case1_graph
from app.agents.graphs.case2 import build_case2_graph
from app.agents.graphs.general import build_general_graph
from app.agents.llm import should_skip_agent
from app.agents.progress import ProgressLogger
from app.config import settings


ProgressCallback = Optional[Callable[[str], None]]


def _select_builder(task_kind: str | None):
    kind = (task_kind or "general").lower()
    if kind == "case1":
        return build_case1_graph
    if kind == "case2":
        return build_case2_graph
    return build_general_graph


def run_agent(
    extract_root: Path,
    outputs_dir: Path,
    *,
    task_id: str | None = None,
    task_kind: str | None = None,
    on_progress: ProgressCallback = None,
) -> tuple[int, str, str]:
    """
    Invoke the LangGraph agent for the given extract workspace.

    Returns (code, combined_log_tail, stderr_tail) — same contract as run_claude.
    """
    outputs_dir.mkdir(parents=True, exist_ok=True)
    log_file = outputs_dir / "agent.log"
    # Keep claude.log as symlink/copy alias for API compatibility
    claude_log_alias = outputs_dir / "claude.log"

    logger = ProgressLogger(
        task_id=task_id, on_progress=on_progress, log_path=log_file
    )
    logger.log(
        f"LangGraph agent start: task_kind={task_kind or 'general'} "
        f"provider={settings.llm_provider} model={settings.llm_model}"
    )

    if should_skip_agent():
        logger.log("SKIP_AGENT=true, 跳过智能体执行")
        text = logger.tail()
        claude_log_alias.write_text(text, encoding="utf-8")
        return 0, text, ""

    kind = task_kind or "general"
    initial: dict[str, Any] = {
        "task_id": task_id or "",
        "task_kind": kind,
        "extract_root": str(extract_root.resolve()),
        "log_lines": [],
        "errors": [],
        "fix_round": 0,
    }

    err_tail = ""
    code = 1
    try:
        with open_checkpointer(extract_root) as checkpointer:
            builder = _select_builder(kind)
            graph = builder(checkpointer=checkpointer)
            config = thread_config(task_id or extract_root.name)
            config["max_concurrency"] = max(1, settings.agent_parallel_workers)
            # Stream updates for progress
            for event in graph.stream(
                initial,
                config=config,
                stream_mode="updates",
            ):
                if not isinstance(event, dict):
                    continue
                for node_name, update in event.items():
                    if not isinstance(update, dict):
                        continue
                    progress = update.get("progress")
                    if progress:
                        logger.log(f"[{node_name}] {progress}")
                    for line in update.get("log_lines") or []:
                        if line and line != progress:
                            logger.log(f"[{node_name}] {line}")
                    for err in update.get("errors") or []:
                        if err:
                            logger.log(f"[{node_name}] ERROR: {err}")
                            err_tail = (err_tail + "\n" + err)[-2000:]
            code = 0
            logger.log("LangGraph agent finished")
    except Exception as exc:  # noqa: BLE001
        code = 1
        tb = traceback.format_exc()
        err_tail = (str(exc) + "\n" + tb)[-2000:]
        logger.log(f"LangGraph agent failed: {exc}")
        if settings.agent_stream_to_console:
            sys.stderr.write(tb)
            sys.stderr.flush()

    text = logger.tail()
    try:
        claude_log_alias.write_text(
            log_file.read_text(encoding="utf-8", errors="replace")
            if log_file.is_file()
            else text,
            encoding="utf-8",
        )
    except OSError:
        pass
    return code, text, err_tail

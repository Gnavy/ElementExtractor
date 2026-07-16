"""Run backend/scripts helpers inside an extract_root (deterministic nodes)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.config import settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def run_tool_script(
    extract_root: Path,
    script_name: str,
    args: list[str],
    *,
    timeout: int = 180,
    env_extra: dict[str, str] | None = None,
) -> tuple[bool, str]:
    script = _SCRIPTS_DIR / script_name
    if not script.is_file():
        return False, f"脚本不存在: {script_name}"
    cmd = [sys.executable, str(script), *args]
    env = os.environ.copy()
    env["OCR_CONFIDENCE_THRESHOLD"] = str(settings.ocr_confidence_threshold)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(extract_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"{script_name} 超时 ({timeout}s)"
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, out[-3000:]
    return True, out[-3000:]

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings


def ocr_guards_enabled(task_kind: str) -> bool:
    """OCR 增强（文本层体检、双栏拆分）是否对该场景生效。

    这两项是为财务报表设计的；case0 材料杂、单任务几十份文件，收益未验证而
    误判代价高——把一份准确的文本层换成 OCR 结果是倒退。默认只开 case2。
    """
    kinds = [k.strip() for k in (settings.ocr_guard_kinds or "").split(",") if k.strip()]
    return not kinds or (task_kind or "") in kinds


def run_ocr(
    extract_root: Path,
    log_path: Optional[Path] = None,
    task_kind: str = "",
) -> Tuple[int, str]:
    """
    Run docling conversion: PDF OCR; PPTX via LibreOffice -> PDF -> RapidOCR.
    Prefer OCR_PYTHON if set, else ``conda run -n <conda_env>``.
    """
    script = settings.ocr_script.resolve()
    if not script.exists():
        return 1, f"OCR script missing: {script}"

    py = settings.ocr_python
    if py is not None:
        py = py.expanduser().resolve()
        if not py.exists():
            return 1, f"OCR_PYTHON 不存在: {py}"
        cmd = [str(py), str(script), "--root", str(extract_root)]
    else:
        cmd = [
            settings.conda_bin,
            "run",
            "-n",
            settings.conda_env,
            "python",
            str(script),
            "--root",
            str(extract_root),
        ]
    env = os.environ.copy()
    env["LIBREOFFICE_BIN"] = settings.libreoffice_bin
    env["PPTX_CONVERT_TIMEOUT_SEC"] = str(settings.pptx_convert_timeout_sec)
    env["OCR_CONFIDENCE_THRESHOLD"] = str(settings.ocr_confidence_threshold)
    # 以下三项默认都不注入，保持原有行为；取值说明见 config.Settings 对应字段
    if settings.hf_offline:
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
    if settings.omp_wait_policy.strip():
        env["OMP_WAIT_POLICY"] = settings.omp_wait_policy.strip().upper()
    if settings.docling_num_threads is not None:
        env["DOCLING_NUM_THREADS"] = str(settings.docling_num_threads)
    guards_on = ocr_guards_enabled(task_kind)
    env["OCR_TEXT_LAYER_GUARD"] = "1" if (guards_on and settings.ocr_text_layer_guard) else "0"
    env["OCR_TABLE_SPLIT"] = "1" if (guards_on and settings.ocr_table_split) else "0"

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=7200,
        env=env,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(out, encoding="utf-8", errors="replace")
    return proc.returncode, out[-8000:] if len(out) > 8000 else out

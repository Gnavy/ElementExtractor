import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings


def run_ocr(extract_root: Path, log_path: Optional[Path] = None) -> Tuple[int, str]:
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
    # docling 启动时会联网校验 HuggingFace 上的 layout/TableFormer 模型，
    # 隔离网里连不上要白等约 260 秒（与页数无关）。模型缓存已离线部署，强制走本地。
    # 副作用：缓存里没有的模型不会自动下载，会直接报错——这是期望行为。
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

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

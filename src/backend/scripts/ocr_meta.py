"""OCR 产物指纹：OCR 代码或开关变了，历史 ocr_text 就不该再被复用。

复用只按材料 md5 匹配，不看产物是用哪版代码跑出来的。于是改完 OCR 链路后，
同材料的新任务会静默复用旧 markdown，新代码一行都不生效，日志里只有一句
`OCR skipped`，从产物上完全看不出来。2026-07-31 改文本层守卫和双栏拆分时
差点踩上——只因历史任务的 zip md5 是 `df376a6` 修稳定之前算的、对不上才幸免。

纯标准库实现：OCR 子进程（v312）与 worker（v311）两个环境都要能导入，
不能依赖 pydantic / app.config。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

META_NAME = ".ocr_meta.json"

# 这些脚本共同决定 ocr_text 的内容，任一改动都应让历史产物失效
_FINGERPRINT_SOURCES = (
    "ocr_pdf.py",
    "text_layer_guard.py",
    "table_split.py",
    "ocr_confidence_export.py",
    "pptx_to_markdown.py",
)


def code_fingerprint() -> str:
    """OCR 相关脚本内容的哈希；改一个字符指纹就变。"""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in sorted(_FINGERPRINT_SOURCES):
        path = here / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()[:16]


def write_meta(ocr_dir: Path, switches: dict[str, Any]) -> None:
    """OCR 成功后记下用的哪版代码、哪组开关。"""
    ocr_dir.mkdir(parents=True, exist_ok=True)
    payload = {"code": code_fingerprint(), "switches": dict(switches)}
    (ocr_dir / META_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def read_meta(ocr_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((ocr_dir / META_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def meta_matches(ocr_dir: Path, switches: dict[str, Any]) -> bool:
    """产物是否由当前这版代码和开关跑出来的。

    没有 meta 文件一律返回 False——上线后历史产物会失效一次，这是安全方向：
    宁可多跑一遍 OCR，也不要拿旧产物冒充新的。
    """
    meta = read_meta(ocr_dir)
    if meta is None:
        return False
    if meta.get("code") != code_fingerprint():
        return False
    return dict(meta.get("switches") or {}) == dict(switches)

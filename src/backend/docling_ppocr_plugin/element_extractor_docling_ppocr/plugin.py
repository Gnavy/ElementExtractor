from __future__ import annotations


def ocr_engines():
    """Register the local PaddleOCR adapter with Docling."""
    from .model import PaddleOcrModel

    return {"ocr_engines": [PaddleOcrModel]}

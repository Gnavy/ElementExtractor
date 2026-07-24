from __future__ import annotations

from typing import ClassVar, Literal

from docling.datamodel.pipeline_options import OcrOptions


class PaddleOcrOptions(OcrOptions):
    """Options for the local official PaddleOCR PP-OCR pipeline."""

    kind: ClassVar[Literal["paddleocr"]] = "paddleocr"
    lang: list[str] = ["ch"]
    ocr_version: Literal["PP-OCRv5"] = "PP-OCRv5"
    text_rec_score_thresh: float = 0.0

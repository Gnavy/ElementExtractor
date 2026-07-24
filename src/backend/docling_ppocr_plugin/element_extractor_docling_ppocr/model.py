from __future__ import annotations

import io
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Type

import numpy
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.models.base_ocr_model import BaseOcrModel
from docling.utils.profiling import TimeRecorder
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .options import PaddleOcrOptions


class PaddleOcrModel(BaseOcrModel):
    """Run PaddleOCR (in-process, or via PADDLEOCR_SERVICE_URL HTTP service) and
    return Docling OCR cells."""

    def __init__(
        self,
        *,
        enabled: bool,
        artifacts_path: Path | None,
        options: PaddleOcrOptions,
        accelerator_options: AcceleratorOptions,
    ):
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: PaddleOcrOptions
        self.scale = 3
        # 设置 PADDLEOCR_SERVICE_URL 后走容器服务；lang/ocr_version/text_rec_score_thresh
        # 在该模式下由服务启动时的环境变量决定，与本地模式各自独立配置
        self.service_url = os.environ.get("PADDLEOCR_SERVICE_URL", "").strip() or None
        if enabled and not self.service_url:
            from paddleocr import PaddleOCR

            self.reader = PaddleOCR(
                lang=self.options.lang[0] if self.options.lang else "ch",
                ocr_version=self.options.ocr_version,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_rec_score_thresh=self.options.text_rec_score_thresh,
            )

    def _predict(self, image) -> dict | None:
        """Run OCR on one page image; returns a dict shaped like PaddleOCR's own
        predict() result ({"rec_texts": [...], "rec_scores": [...], "dt_polys": [...]})
        whether it came from the local reader or the remote service."""
        if self.service_url:
            import requests

            buf = io.BytesIO()
            image.save(buf, format="PNG")
            resp = requests.post(
                f"{self.service_url.rstrip('/')}/ocr",
                files={"image": ("page.png", buf.getvalue(), "image/png")},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()

        result = self.reader.predict(numpy.array(image))
        return result[0] if result else None

    def __call__(
        self, conv_res: ConversionResult, page_batch: Iterable[Page]
    ) -> Iterable[Page]:
        if not self.enabled:
            yield from page_batch
            return

        for page in page_batch:
            assert page._backend is not None
            if not page._backend.is_valid():
                yield page
                continue

            with TimeRecorder(conv_res, "ocr"):
                cells: list[TextCell] = []
                for ocr_rect in self.get_ocr_rects(page):
                    if ocr_rect.area() == 0:
                        continue
                    image = page._backend.get_page_image(
                        scale=self.scale, cropbox=ocr_rect
                    )
                    ocr_result = self._predict(image)
                    if not ocr_result:
                        continue
                    for text, score, polygon in zip(
                        ocr_result.get("rec_texts", []),
                        ocr_result.get("rec_scores", []),
                        ocr_result.get("dt_polys", []),
                    ):
                        points = numpy.asarray(polygon, dtype=float)
                        if points.size == 0:
                            continue
                        x0, y0 = points.min(axis=0)
                        x1, y1 = points.max(axis=0)
                        cells.append(
                            TextCell(
                                index=len(cells),
                                text=str(text),
                                orig=str(text),
                                confidence=float(score),
                                from_ocr=True,
                                rect=BoundingRectangle.from_bounding_box(
                                    BoundingBox.from_tuple(
                                        coord=(
                                            (x0 / self.scale) + ocr_rect.l,
                                            (y0 / self.scale) + ocr_rect.t,
                                            (x1 / self.scale) + ocr_rect.l,
                                            (y1 / self.scale) + ocr_rect.t,
                                        ),
                                        origin=CoordOrigin.TOPLEFT,
                                    )
                                ),
                            )
                        )
                self.post_process_cells(cells, page)
            yield page

    @classmethod
    def get_options_type(cls) -> Type[PaddleOcrOptions]:
        return PaddleOcrOptions

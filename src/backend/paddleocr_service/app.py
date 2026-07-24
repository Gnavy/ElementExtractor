"""独立 PaddleOCR 识别服务：图进，文字/置信度/坐标出。
启动时按环境变量初始化一次 PaddleOCR reader 并常驻，供 docling_ppocr_plugin 通过 HTTP 调用，
避免宿主机 glibc 过旧无法直接安装新版 paddlepaddle 的问题（本服务运行在现代 glibc 镜像内）。
"""

from __future__ import annotations

import io
import os

import numpy
from fastapi import FastAPI, File, UploadFile
from paddleocr import PaddleOCR
from PIL import Image

app = FastAPI()

_reader = PaddleOCR(
    lang=os.environ.get("PADDLEOCR_LANG", "ch"),
    ocr_version=os.environ.get("PADDLEOCR_VERSION", "PP-OCRv5"),
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    text_rec_score_thresh=float(os.environ.get("PADDLEOCR_SCORE_THRESH", "0.0")),
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(image: UploadFile = File(...)):
    data = await image.read()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    result = _reader.predict(numpy.array(img))
    if not result:
        return {"rec_texts": [], "rec_scores": [], "dt_polys": []}
    ocr_result = result[0]
    return {
        "rec_texts": list(ocr_result.get("rec_texts", [])),
        "rec_scores": [float(s) for s in ocr_result.get("rec_scores", [])],
        "dt_polys": [
            poly.tolist() if hasattr(poly, "tolist") else poly
            for poly in ocr_result.get("dt_polys", [])
        ],
    }

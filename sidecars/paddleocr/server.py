"""FastAPI wrapper around PaddleOCR that speaks the Forge `ocr_document`
contract (see backend/templates/runtime/workflows/OCR_SIDECAR.md).

POST /ocr accepts either:
  - {"file_url": "..."}                       — sidecar fetches
  - {"file_b64": "...", "mime_type": "..."}  — inline base64
Optional: pages (list[int], 1-indexed), language (str; PaddleOCR code).

Returns {text, pageCount, confidence, blocks: [{text, bbox, confidence, page}]}.
"""
import base64
import io
import tempfile
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# One PaddleOCR instance per language, lazy-initialised. Loading models is the
# expensive part (~30-500MB depending on lang) so we cache them.
_ocr_cache: dict[str, "PaddleOCR"] = {}  # type: ignore[name-defined]


def _get_ocr(lang: str):
    from paddleocr import PaddleOCR  # imported lazily so container starts fast
    key = (lang or "en").lower()
    if key not in _ocr_cache:
        _ocr_cache[key] = PaddleOCR(
            use_angle_cls=True,
            lang=key,
            show_log=False,
        )
    return _ocr_cache[key]


app = FastAPI(title="Forge PaddleOCR Sidecar", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True, "engine": "paddleocr", "cached_langs": list(_ocr_cache)}


class OcrIn(BaseModel):
    file_url: Optional[str] = None
    file_b64: Optional[str] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    pages: Optional[list[int]] = None
    language: Optional[str] = None


@app.post("/ocr")
async def do_ocr(body: OcrIn):
    if body.file_url:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(body.file_url)
            resp.raise_for_status()
            data = resp.content
            mime = body.mime_type or resp.headers.get("content-type", "").split(";")[0]
    elif body.file_b64:
        try:
            data = base64.b64decode(body.file_b64)
        except Exception as exc:
            raise HTTPException(400, f"file_b64 invalid: {exc}")
        mime = body.mime_type or "application/octet-stream"
    else:
        raise HTTPException(400, "file_url or file_b64 required")

    suffix = ".pdf" if "pdf" in (mime or "").lower() else ".png"
    lang = body.language or "en"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            ocr = _get_ocr(lang)
            raw = ocr.ocr(tmp.name, cls=True)
        except Exception as exc:
            raise HTTPException(500, f"paddleocr failed: {exc}")

    # PaddleOCR returns [page1_lines, page2_lines, …] with each line as
    # [ [poly4], (text, confidence) ]. Some page slots can be None.
    blocks = []
    all_text: list[str] = []
    pages_out = 0
    for page_idx, page in enumerate(raw or [], start=1):
        if body.pages and page_idx not in body.pages:
            continue
        if not page:
            pages_out += 1
            continue
        for line in page:
            try:
                poly, (txt, conf) = line
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                blocks.append({
                    "text": str(txt),
                    "bbox": [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
                    "confidence": float(conf),
                    "page": page_idx,
                })
                all_text.append(str(txt))
            except Exception:
                # Malformed line — skip rather than fail the batch.
                continue
        pages_out += 1

    mean_conf = (sum(b["confidence"] for b in blocks) / len(blocks)) if blocks else 0.0
    return {
        "text": "\n".join(all_text),
        "pageCount": pages_out,
        "confidence": mean_conf,
        "blocks": blocks,
    }

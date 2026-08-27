# PaddleOCR sidecar — running your own OCR service

The `ocr_document` workflow action calls an HTTP sidecar hosted by the operator.
Point it at any service that speaks the contract below — a stock PaddleOCR
container behind a thin wrapper, a hosted `paddleocr-server` fork, or a custom
OCR pipeline your team already runs. Because the URL is configured per
integration (not baked into the app), banking / healthcare / gov customers can
run the whole workflow **on-prem** with zero data leaving their network.

## Contract

The handler (`backend/templates/runtime/workflows/ocr.ts`) POSTs to
`{PADDLEOCR_URL}/ocr`. Trailing `/ocr` on the URL is fine — it's not doubled.

**Request** — one of two bodies, auto-picked by the handler:

```jsonc
// (a) File already reachable to the sidecar — preferred (no b64 payload).
{ "file_url": "https://app.example.com/api/files/abc-123",
  "pages":    [1, 2, 3],   // optional; 1-indexed
  "language": "en" }       // optional; ISO 639-1, PaddleOCR code

// (b) Fallback when the file lives inside the app's file store and the sidecar
//     can't reach it — handler loads the bytes and sends them inline.
{ "file_b64":  "JVBERi0xLjcK...",
  "mime_type": "application/pdf",
  "filename":  "statement.pdf",
  "pages":     [1],
  "language":  "en" }
```

Auth (optional): if `PADDLEOCR_API_KEY` is configured, the handler adds
`Authorization: Bearer <key>` — leave the env var unset for open sidecars.

**Response** — one JSON object:

```jsonc
{ "text":       "ACCOUNT STATEMENT\nCustomer …",   // full extracted text
  "pageCount":  3,
  "confidence": 0.94,           // mean 0..1 across blocks
  "blocks": [                   // per-word / per-line boxes
    { "text": "ACCOUNT",
      "bbox": [x, y, w, h],     // pixel coords, page-relative
      "confidence": 0.98,
      "page": 1 },
    …
  ] }
```

Snake-case aliases (`page_count`) are accepted for `pageCount`. Missing fields
are treated as empty (`text: ""`, `blocks: []`, `pageCount: 0`, `confidence: 0`).

## Quickest sidecar: `paddleocr` + a 30-line FastAPI wrapper

```dockerfile
# Dockerfile
FROM paddlepaddle/paddleocr:latest
RUN pip install fastapi uvicorn python-multipart httpx
COPY server.py /app/server.py
WORKDIR /app
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

```python
# server.py
import base64, io, httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from paddleocr import PaddleOCR

app = FastAPI()
ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

class OcrIn(BaseModel):
    file_url: str | None = None
    file_b64: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    pages: list[int] | None = None
    language: str | None = None

@app.post("/ocr")
async def do_ocr(body: OcrIn):
    if body.file_url:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(body.file_url)
            r.raise_for_status()
            data = r.content
    elif body.file_b64:
        data = base64.b64decode(body.file_b64)
    else:
        raise HTTPException(400, "file_url or file_b64 required")

    # PaddleOCR wants a file path or ndarray — quickest is a NamedTemporaryFile.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf" if (body.mime_type or "").endswith("pdf") else ".png", delete=True) as f:
        f.write(data); f.flush()
        result = ocr.ocr(f.name, cls=True)

    blocks = []
    all_text = []
    for page_idx, page in enumerate(result or [], start=1):
        for line in (page or []):
            bbox_poly, (txt, conf) = line
            xs = [p[0] for p in bbox_poly]; ys = [p[1] for p in bbox_poly]
            blocks.append({
                "text": txt,
                "bbox": [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
                "confidence": float(conf),
                "page": page_idx,
            })
            all_text.append(txt)
    mean_conf = sum(b["confidence"] for b in blocks) / max(len(blocks), 1)
    return {"text": "\n".join(all_text), "pageCount": len(result or []),
            "confidence": mean_conf, "blocks": blocks}
```

Run it:

```bash
docker build -t forge-paddleocr .
docker run -d -p 8000:8000 --name forge-paddleocr forge-paddleocr
```

Then in the generated app's `/settings/integrations` UI, set:

- **PaddleOCR sidecar URL** → `http://forge-paddleocr:8000` (or the reachable
  hostname of your container).
- **Sidecar API key** → leave blank unless you add auth to the wrapper.

## Language codes

PaddleOCR ships models per language family. Common codes: `en`, `ch` (Chinese
simp+trad), `chinese_cht`, `ta` (Tamil), `te` (Telugu), `ka` (Kannada), `ja`
(Japanese), `ko` (Korean), `ar` (Arabic), `hi` (Hindi), `ru`, `de`, `fr`, `es`,
`it`, `pt`. Leave `ocrLanguage` empty in the workflow node to fall through to the
sidecar's default (typically `en`).

## Failure behaviour

- **URL not set** — in dev, `ocr_document` returns an empty result so the
  workflow doesn't halt during local development. In production (or with
  `FORGE_OCR_STRICT=1`), it throws — the run is marked failed.
- **Sidecar unreachable / non-2xx** — logged as a warning, empty result
  returned so downstream nodes see zeroed outputs. Set `FORGE_OCR_STRICT=1` to
  fail the run instead.
- **Malformed response** — coerced field-by-field (`text` defaults to `""`,
  `blocks` to `[]`, etc.). Never crashes the workflow on shape mismatches.

## Verifying end-to-end

1. Configure PADDLEOCR_URL in `/settings/integrations` (or `.env.local`).
2. Trigger a workflow with an `ocr_document` step that receives a file via
   `{{input}}`.
3. Check the run log — you should see `text` populated on the OCR node's
   output, and downstream `db_insert` steps binding `{{text}}` / `{{blocks}}`
   should persist the extracted content.

"""FastAPI wrapper around open_clip that speaks the Forge embedding contract
(see backend/templates/runtime/embeddings.ts).

POST /embed accepts exactly one of:
  - {"image_b64": "...", "mime_type": "image/png"}   — inline base64
  - {"image_url": "https://..."}                     — the sidecar fetches it
  - {"text": "a red leather armchair"}               — a text query

Returns {"vector": [...], "dimensions": 512, "model": "ViT-B-32/laion2b_s34b_b79k"}.

Images and text are embedded into the SAME space, so a photo can be found by
another photo or by a sentence. Vectors are L2-normalised: cosine distance in
pgvector (`<=>`) is then 1 - dot product.

If EMBEDDINGS_API_KEY is set, requests must carry `Authorization: Bearer <key>`.
"""
from __future__ import annotations

import base64
import io
import os
import threading
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.environ.get("CLIP_MODEL", "ViT-B-32")
PRETRAINED = os.environ.get("CLIP_PRETRAINED", "laion2b_s34b_b79k")
API_KEY = os.environ.get("EMBEDDINGS_API_KEY", "")
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))

_lock = threading.Lock()
_state: dict = {}


def _model():
    """Load once, lazily — the weights are baked into the image at build time,
    so this is a disk read, not a download."""
    with _lock:
        if "model" not in _state:
            import open_clip
            import torch

            torch.set_num_threads(max(1, int(os.environ.get("TORCH_THREADS", "2"))))
            model, _, preprocess = open_clip.create_model_and_transforms(
                MODEL_NAME, pretrained=PRETRAINED)
            model.eval()
            _state.update(model=model, preprocess=preprocess,
                          tokenizer=open_clip.get_tokenizer(MODEL_NAME), torch=torch)
        return _state


app = FastAPI(title="Forge CLIP embedding sidecar", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True, "model": f"{MODEL_NAME}/{PRETRAINED}", "loaded": "model" in _state}


class EmbedIn(BaseModel):
    image_b64: Optional[str] = None
    mime_type: Optional[str] = None
    image_url: Optional[str] = None
    text: Optional[str] = None


def _normalised(t) -> list[float]:
    t = t / t.norm(dim=-1, keepdim=True)
    return [float(x) for x in t[0].tolist()]


async def _image_bytes(body: EmbedIn) -> bytes:
    if body.image_b64:
        try:
            data = base64.b64decode(body.image_b64)
        except Exception as exc:
            raise HTTPException(400, f"image_b64 invalid: {exc}")
    else:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(body.image_url)
            resp.raise_for_status()
            data = resp.content
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"image is {len(data)} bytes; the limit is {MAX_IMAGE_BYTES}")
    return data


@app.post("/embed")
async def embed(body: EmbedIn, authorization: Optional[str] = Header(default=None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "missing or wrong bearer token")
    given = [k for k in ("image_b64", "image_url", "text") if getattr(body, k)]
    if len(given) != 1:
        raise HTTPException(400, "send exactly one of image_b64, image_url, text")

    s = _model()
    torch = s["torch"]
    with torch.no_grad():
        if body.text:
            tokens = s["tokenizer"]([body.text.strip()[:1000]])
            vec = _normalised(s["model"].encode_text(tokens))
        else:
            from PIL import Image, UnidentifiedImageError

            data = await _image_bytes(body)
            try:
                image = Image.open(io.BytesIO(data)).convert("RGB")
            except UnidentifiedImageError:
                raise HTTPException(415, "not an image this service can read")
            vec = _normalised(s["model"].encode_image(s["preprocess"](image).unsqueeze(0)))
    return {"vector": vec, "dimensions": len(vec), "model": f"{MODEL_NAME}/{PRETRAINED}"}

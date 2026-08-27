"""Brand extraction endpoints.

POST /api/brand/extract/logo   — multipart, logo file → palette
POST /api/brand/extract/url    — JSON {url}, scrape og:image → palette
"""
from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from pydantic import BaseModel
from services.brand_extractor import extract_palette_from_logo
from services.color_theory import derive_palette
from services.url_brand_scraper import scrape_brand_from_url

router = APIRouter()


class _ExtractURLRequest(BaseModel):
    url: str


def _palette_to_full_response(primary_hex: str, secondary_hex: str | None) -> dict:
    derived = derive_palette(primary_hex, secondary_hint=secondary_hex)
    return {
        "primary_hex": primary_hex,
        "secondary_hex": secondary_hex,
        "derived": {
            "primary": derived.primary,
            "secondary": derived.secondary,
            "accent": derived.accent,
            "background": derived.background,
            "surface": derived.surface,
            "text_primary": derived.text_primary,
            "text_secondary": derived.text_secondary,
            "border": derived.border,
            "success": derived.success,
            "warning": derived.warning,
            "error": derived.error,
        },
    }


@router.post("/api/brand/extract/logo")
async def extract_from_logo(logo: UploadFile = File(...)):
    data = await logo.read()
    try:
        palette = extract_palette_from_logo(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not parse logo: {e}")
    return _palette_to_full_response(palette.primary_hex, palette.secondary_hex)


@router.post("/api/brand/extract/url")
async def extract_from_url(req: _ExtractURLRequest = Body(...)):
    result = scrape_brand_from_url(req.url)
    if result is None:
        raise HTTPException(status_code=404, detail="no og:image found at URL")
    response = _palette_to_full_response(result.primary_hex, result.palette.secondary_hex)
    response["title"] = result.title
    response["og_image_url"] = result.og_image_url
    return response

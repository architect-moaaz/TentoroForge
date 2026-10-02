"""Brand endpoints — the palette a logo implies, and the logo itself.

POST   /api/brand/extract/logo            — multipart, logo file → palette
POST   /api/brand/extract/url             — JSON {url}, scrape og:image → palette
POST   /api/projects/{id}/brand/logo      — multipart, logo file → the app carries it
DELETE /api/projects/{id}/brand/logo      — the app stops carrying it

The first two read a logo and keep only the colours. That asymmetry is what
`designSystem.logo` and the two routes below close: the same image that gives
an application its green can now also appear in the corner of its screens.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.brand_extractor import extract_palette_from_logo
from services.color_theory import derive_palette
from services.project_service import get_project_with_auth
from services.url_brand_scraper import scrape_brand_from_url

logger = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------- #
# the logo itself
# --------------------------------------------------------------------------- #

@router.post("/api/projects/{project_id}/brand/logo")
async def set_project_logo(
    project_id: uuid.UUID,
    logo: UploadFile = File(...),
    alt: str = Form(""),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Give this application its mark.

    A separate door from the chat composer's attachments on purpose. An
    attachment is bounded by what the vision API can look at, which rules out
    SVG — the format most brand marks actually arrive in — and nothing here
    asks a model to look at the file. It is also a designation, not a hand-off:
    most images an owner sends are screenshots of something that is wrong, and
    `services/design_reference.py` already learned that designation has to be
    explicit.

    Stored beside the Blueprint and recorded in `designSystem.logo`, through
    the one seam that writes it, so the application carries the mark rather
    than the conversation holding it.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=409,
                            detail="this project has nothing generated yet")

    from services import brand_logo
    from services.smith.brand_logo_change import run as set_logo_run

    data = await logo.read()
    try:
        body = brand_logo.store(project.output_dir, logo.filename or "logo",
                                logo.content_type or "", data)
    except brand_logo.BrandLogoError as exc:
        # 400, not 500: a wrong file type or an oversized upload is something
        # the person on the other end can fix, and the message is written to
        # be shown to them verbatim.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = set_logo_run(project.output_dir, logo=body, alt=alt)
    if not out.get("applied"):
        raise HTTPException(status_code=409, detail=out.get("reason") or "could not set the logo")
    logger.info("brand logo set: project=%s file=%s", project_id, body["file"])
    return {"logo": out["logo"], "edited_paths": out["edited_paths"],
            "version": out["version"], "summary": out["diff_summary"]}


@router.delete("/api/projects/{project_id}/brand/logo")
async def clear_project_logo(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Take the mark back off; the rail returns to the application's initial."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=409,
                            detail="this project has nothing generated yet")

    from services.smith.brand_logo_change import run as set_logo_run

    out = set_logo_run(project.output_dir, remove=True)
    if not out.get("applied"):
        raise HTTPException(status_code=409, detail=out.get("reason") or "could not remove the logo")
    return {"logo": None, "edited_paths": out["edited_paths"],
            "version": out["version"], "summary": out["diff_summary"]}

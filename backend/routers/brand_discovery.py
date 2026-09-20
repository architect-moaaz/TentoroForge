"""The company profile an organisation carries — read once, edited forever.

    POST   /api/orgs/{org_id}/brand/discover   read a URL, write the profile
    GET    /api/orgs/{org_id}/brand            the profile, or null
    PUT    /api/orgs/{org_id}/brand            correct it; design.md regenerated
    POST   /api/orgs/{org_id}/brand/skip       asked, declined, resumable
    GET    /api/orgs/{org_id}/brand/logo       the stored mark
    GET    /api/orgs/{org_id}/brand/design.md  the document, as a document

TWO ROLES, TWO PERMISSIONS. Reading the profile is a member's right — every
person building an app for this company needs to see what it will look like.
Changing it is an admin's, because a colour changed here changes every
application built afterwards, and one person's preference is not the
company's design language.

WHY A PLAIN POST AND NOT A STREAM. Discovery is one read of one page: a
render, a summary and an image fetch, twenty seconds at the worst. The SSE
machinery elsewhere in this codebase exists for runs measured in minutes with
a progress bar worth watching. A spinner is the honest UI for this one.

THE PROFILE IS ALWAYS EDITABLE. Everything discovery produces is a first
draft — `PUT` takes corrections for any part of it and re-renders design.md in
the same call, so the document and the structure can never disagree
(`services.brand_discovery.design_md` says why that matters).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.brand_profile import BrandDiscoveryStatus, OrgBrandProfile
from models.org import OrgMemberRole
from routers.orgs import _require_org_member

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand"])


# --------------------------------------------------------------------------- #
# shapes
# --------------------------------------------------------------------------- #

class DiscoverRequest(BaseModel):
    url: str = Field(..., min_length=3, max_length=500)


class BrandProfileUpdate(BaseModel):
    """A correction. Every field optional — this is a patch, not a replacement.

    `design` and `identity` are replaced wholesale when given rather than
    deep-merged, because the editor sends the whole object back and a merge
    would make a *removed* colour role impossible to express.
    """

    company_name: str | None = Field(default=None, max_length=255)
    identity: dict[str, Any] | None = None
    design: dict[str, Any] | None = None


class BrandProfileResponse(BaseModel):
    status: str
    source_url: str | None = None
    company_name: str | None = None
    failure_reason: str | None = None
    identity: dict[str, Any] = Field(default_factory=dict)
    design: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    design_md: str = ""
    #: Whether a build can actually be offered this language. `ready` with an
    #: empty palette is not something to offer anyone, and the client should
    #: not have to re-derive that rule.
    usable: bool = False
    has_logo: bool = False


def _response(profile: OrgBrandProfile | None) -> BrandProfileResponse | None:
    if profile is None:
        return None
    return BrandProfileResponse(
        status=profile.status.value if hasattr(profile.status, "value")
        else str(profile.status),
        source_url=profile.source_url,
        company_name=profile.company_name,
        failure_reason=profile.failure_reason,
        identity=profile.identity or {},
        design=profile.design or {},
        evidence=profile.evidence or {},
        design_md=profile.design_md or "",
        usable=profile.usable,
        has_logo=bool(profile.logo_path),
    )


async def _load(org_id: uuid.UUID, db: AsyncSession) -> OrgBrandProfile | None:
    found = await db.execute(
        select(OrgBrandProfile).where(OrgBrandProfile.org_id == org_id))
    return found.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #

@router.get("/api/orgs/{org_id}/brand", response_model=BrandProfileResponse | None)
async def get_brand_profile(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The company profile, or `null` when nobody has run discovery.

    `null` rather than a 404: "this organisation has no profile" is a normal
    state that the onboarding card and the Settings tab both render, not an
    error either of them should have to catch.
    """
    await _require_org_member(org_id, user, db)
    return _response(await _load(org_id, db))


@router.post("/api/orgs/{org_id}/brand/discover",
             response_model=BrandProfileResponse)
async def discover_brand(
    org_id: uuid.UUID,
    req: DiscoverRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read the company's website and write the profile.

    Re-runnable: a company that redesigns runs it again and the row is
    replaced, which is also how a `failed` or `skipped` profile is finished
    later from Settings. The previous reading is not kept — `evidence` is
    about the design language on record now, and a history of palettes nobody
    asked for is a table that only grows.
    """
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    from services.brand_discovery import SiteUnreadable, discover

    profile = await _load(org_id, db)
    if profile is None:
        profile = OrgBrandProfile(org_id=org_id, created_by=user.id)
        db.add(profile)

    profile.status = BrandDiscoveryStatus.extracting
    profile.source_url = req.url
    profile.failure_reason = None
    await db.commit()

    try:
        read = await discover(req.url, str(org_id))
    except SiteUnreadable as exc:
        # A refusal the person can act on, not a server fault: the message is
        # written to be shown verbatim and the row keeps the URL so Settings
        # can offer to try it again.
        profile.status = BrandDiscoveryStatus.failed
        profile.failure_reason = str(exc)
        await db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("[brand] discovery failed for %s", req.url)
        profile.status = BrandDiscoveryStatus.failed
        profile.failure_reason = (
            "Something went wrong reading that site. You can try again, or "
            "skip this and fill it in by hand.")
        await db.commit()
        raise HTTPException(status_code=502, detail=profile.failure_reason) from exc

    for key, value in read.items():
        setattr(profile, key, value)
    profile.status = BrandDiscoveryStatus.ready
    await db.commit()
    await db.refresh(profile)
    logger.info("[brand] %s discovered from %s (usable=%s)",
                org_id, req.url, profile.usable)
    return _response(profile)


@router.put("/api/orgs/{org_id}/brand", response_model=BrandProfileResponse)
async def update_brand_profile(
    org_id: uuid.UUID,
    req: BrandProfileUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Correct the profile. design.md is re-rendered from what results.

    Also the way a profile is created by hand: an organisation whose site
    could not be read, or who never had one, still gets a design language by
    typing it here. That is why this does not require an existing row.
    """
    await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)

    from services.brand_discovery import regenerate

    profile = await _load(org_id, db)
    if profile is None:
        profile = OrgBrandProfile(org_id=org_id, created_by=user.id)
        db.add(profile)

    if req.company_name is not None:
        profile.company_name = req.company_name.strip() or None
    if req.identity is not None:
        profile.identity = req.identity
    if req.design is not None:
        # The mark is not editable through this door — it is bytes in the
        # brand store, and a JSON body naming a different file would point
        # `designSystem.logo` at something nobody uploaded.
        kept = (profile.design or {}).get("logo")
        design = dict(req.design)
        design.pop("logo", None)
        if kept:
            design["logo"] = kept
        profile.design = design

    profile.design_md = regenerate({
        "company_name": profile.company_name,
        "source_url": profile.source_url,
        "identity": profile.identity or {},
        "design": profile.design or {},
        "evidence": profile.evidence or {},
    })
    # An edited profile is a finished one, whatever it was before: somebody
    # has now said what this company looks like, which is the whole of what
    # `ready` means.
    profile.status = BrandDiscoveryStatus.ready
    profile.failure_reason = None
    await db.commit()
    await db.refresh(profile)
    return _response(profile)


@router.post("/api/orgs/{org_id}/brand/skip", response_model=BrandProfileResponse)
async def skip_brand_discovery(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Not now.

    Recorded rather than ignored, because "they were asked and said no" and
    "nobody has ever been asked" are different things to the Settings tab:
    the first is an unfinished task it offers to pick up, the second is a
    feature the organisation has not met. Never destroys a profile that was
    already read — skipping after a successful discovery would be a click
    that silently deletes a design language.
    """
    await _require_org_member(org_id, user, db)

    profile = await _load(org_id, db)
    if profile is None:
        profile = OrgBrandProfile(org_id=org_id, created_by=user.id)
        db.add(profile)
    if profile.status != BrandDiscoveryStatus.ready:
        profile.status = BrandDiscoveryStatus.skipped
    await db.commit()
    await db.refresh(profile)
    return _response(profile)


@router.get("/api/orgs/{org_id}/brand/design.md", response_class=PlainTextResponse)
async def get_design_md(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The document itself, so it can be read, copied, or sent to someone."""
    await _require_org_member(org_id, user, db)
    profile = await _load(org_id, db)
    if profile is None or not profile.design_md:
        raise HTTPException(status_code=404,
                            detail="this organisation has no design language yet")
    return PlainTextResponse(profile.design_md, media_type="text/markdown")


@router.get("/api/orgs/{org_id}/brand/logo")
async def get_brand_logo(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The stored mark. 404 when the company has none."""
    await _require_org_member(org_id, user, db)
    profile = await _load(org_id, db)

    from services.brand_discovery.store import logo_file

    path = logo_file(str(org_id), (profile.design or {}).get("logo")) \
        if profile else None
    if path is None:
        raise HTTPException(status_code=404, detail="no logo on record")
    media = str(((profile.design or {}).get("logo") or {}).get("mediaType")
                or "application/octet-stream")
    return FileResponse(path, media_type=media)

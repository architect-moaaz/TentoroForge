"""Templates made from applications — saved, reviewed by Tentoro, shared in the Gallery.

Save one from any project with a definition: it is a private template its own
organisation can use at once. Add screenshots and submit it, and Tentoro's
admins review it; approved, it is in the Templates Gallery for every
organisation, where people see what it holds, use it, and rate it. What a
template holds and how it is used is `services.project_templates`; its review,
uses and ratings are `services.template_gallery`.

WHO SEES WHAT. A template's own organisation sees it in any state, a Tentoro
admin sees every one, and everyone else sees it only once it is approved. Any
other request answers 404 — the same as a template that does not exist — so a
private template's id reveals nothing about it.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.template_gallery import TemplateListing, TemplateReview
from platform_admin import require_super_admin
from schemas.project import ProjectResponse
from services import project_templates as templates
from services import template_gallery as gallery
from services.project_service import create_project, get_project_with_auth

router = APIRouter(tags=["project-templates"])


class SaveTemplateRequest(BaseModel):
    name: str = Field(default="", max_length=templates.NAME_MAX)
    description: str = Field(default="", max_length=templates.DESCRIPTION_MAX)
    category: str = Field(default="", max_length=60)


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=templates.NAME_MAX)
    description: str | None = Field(default=None, max_length=templates.DESCRIPTION_MAX)
    category: str | None = Field(default=None, max_length=60)


class UseTemplateRequest(BaseModel):
    template_id: str
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name", mode="after")
    @classmethod
    def _a_name_is_words(cls, v: str) -> str:
        # Spaces are not a name: the length was checked before they were trimmed.
        v = v.strip()
        if not v:
            raise ValueError("give the new app a name")
        return v


class SubmitRequest(BaseModel):
    pricing_model: str = Field(default="free", max_length=8)
    price_cents: int | None = Field(default=None, ge=0, le=gallery.PRICE_CENTS_MAX)
    currency: str | None = Field(default=None, max_length=3)


class OrderRequest(BaseModel):
    order: list[str] = Field(default_factory=list, max_length=templates.SCREENSHOT_MAX)


class RateRequest(BaseModel):
    # Strict: `true` and "5" are not star counts (lax parsing read them as 1 and 5).
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(default="", max_length=gallery.COMMENT_MAX)


class CaptionRequest(BaseModel):
    caption: str = Field(default="", max_length=200)


class ModerationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=gallery.NOTE_MAX)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject|remove)$")
    note: str = Field(default="", max_length=gallery.NOTE_MAX)


def _origin(request: Request) -> str:
    return request.headers.get("origin") or ""


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, gallery.GalleryError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


async def _seen(db: AsyncSession, template_id: str, user: PlatformUser, request: Request
                ) -> tuple[dict, TemplateListing | None, gallery.Viewer]:
    """The template, its listing and the caller — or 404 when they may not see it."""
    meta = templates.get(template_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Template not found")
    row = await gallery.listing(db, template_id)
    who = await gallery.viewer(db, meta, user, request.state)
    if not gallery.may_view(gallery.status_of(row), who):
        raise HTTPException(status_code=404, detail="Template not found")
    return meta, row, who


async def _managed(db: AsyncSession, template_id: str, user: PlatformUser, request: Request
                   ) -> tuple[dict, TemplateListing | None, gallery.Viewer]:
    meta, row, who = await _seen(db, template_id, user, request)
    if not gallery.may_manage(meta, who):
        raise HTTPException(status_code=403, detail="Only its builder or an admin of its organisation can change it")
    return meta, row, who


def _editable(row: TemplateListing | None) -> None:
    if gallery.status_of(row) not in gallery.EDITABLE:
        raise HTTPException(status_code=409, detail=(
            "It is in the Gallery as it was approved. Save a new version of the app to change it."))


async def _cards(db: AsyncSession, pairs: list[tuple[dict, TemplateListing | None]],
                 who_for: Any) -> list[dict]:
    """Each template as the client shows it, with its builder, organisation,
    uses and rating — read in one query each, not one per template."""
    lineages = sorted({templates.lineage_of(m) for m, _ in pairs})
    counted = await gallery.stats(db, lineages)
    builders = await gallery.people(db, [m.get("created_by") for m, _ in pairs])
    orgs = await gallery.org_names(db, [m.get("org_id") for m, _ in pairs])
    out = []
    for meta, row in pairs:
        who = await who_for(meta)
        status = gallery.status_of(row)
        manage = gallery.may_manage(meta, who)
        lineage = templates.lineage_of(meta)
        creator = builders.get(str(meta.get("created_by"))) or (
            {"id": str(meta.get("created_by") or ""), "name": meta.get("created_by_name") or "",
             "avatar_url": None} if meta.get("created_by") or meta.get("created_by_name") else None)
        out.append({
            "id": meta["id"], "org_id": meta.get("org_id"), "org_name": orgs.get(str(meta.get("org_id")), ""),
            "name": meta.get("name"), "description": meta.get("description") or "",
            "category": templates.clean_category(meta.get("category")),
            "version": int(meta.get("version") or 1),
            # Which app's template this is a version of — opaque: a lineage
            # names the organisation and source project, which are private.
            "family": hashlib.sha1(lineage.encode()).hexdigest()[:12],
            "status": status, "creator": creator, "created_by": meta.get("created_by"),
            "created_by_name": (creator or {}).get("name") or meta.get("created_by_name") or "",
            "source_project_id": meta.get("source_project_id") if manage or who.is_admin else None,
            "created_at": meta.get("created_at"), "updated_at": meta.get("updated_at"),
            "submitted_at": row.submitted_at.isoformat() if row and row.submitted_at else None,
            "published_at": row.published_at.isoformat() if row and row.published_at else None,
            "review_note": (row.review_note or "") if row and (manage or who.is_admin) else "",
            "pricing": {"model": row.pricing_model if row else "free",
                        "price_cents": row.price_cents if row else None,
                        "currency": row.currency if row else None},
            "summary": meta.get("summary") or {},
            "screenshots": [{k: s.get(k) for k in ("id", "caption", "width", "height", "source")}
                            for s in meta.get("screenshots") or []],
            **counted.get(lineage, {"uses": 0, "rating": None, "ratings": 0}),
            "can_manage": manage, "can_use": gallery.may_use(status, who),
            "can_rate": gallery.may_rate(meta, status, who),
            "own_org": who.in_org,
            "editable": manage and status in gallery.EDITABLE,
        })
    return out


async def _card(db: AsyncSession, meta: dict, row: TemplateListing | None, who: gallery.Viewer) -> dict:
    async def same(_meta: dict) -> gallery.Viewer:
        return who
    return (await _cards(db, [(meta, row)], same))[0]


def _viewer_factory(db: AsyncSession, user: PlatformUser, request: Request):
    cache: dict[str, gallery.Viewer] = {}

    async def who_for(meta: dict) -> gallery.Viewer:
        key = str(meta.get("org_id"))
        if key not in cache:
            cache[key] = await gallery.viewer(db, meta, user, request.state)
        return cache[key]
    return who_for


# --------------------------------------------------------------------------- #
# An organisation's own templates
# --------------------------------------------------------------------------- #

@router.get("/api/orgs/{org_id}/project-templates")
async def list_org_templates(org_id: uuid.UUID, request: Request,
                             user: PlatformUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    if not await gallery.membership(db, str(org_id), user):
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    metas = templates.list_for_org(str(org_id))
    rows = await gallery.listings(db, [m["id"] for m in metas])
    return {"templates": await _cards(db, [(m, rows.get(m["id"])) for m in metas],
                                      _viewer_factory(db, user, request))}


@router.post("/api/projects/{project_id}/templates", status_code=201)
async def save_project_as_template(project_id: uuid.UUID, req: SaveTemplateRequest, request: Request,
                                   user: PlatformUser = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    """Save this project's application as a template — at any point once it has
    a definition, built or not. It starts as a private draft of the organisation."""
    project = await get_project_with_auth(project_id, user, db)
    from routers.blueprint_generate import _output_dir
    try:
        meta = templates.save(output_dir=_output_dir(project), org_id=str(project.org_id),
                              created_by=str(user.id), created_by_name=user.name or "",
                              source_project_id=str(project.id), name=req.name,
                              description=req.description, category=req.category)
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    who = await gallery.viewer(db, meta, user, request.state)
    return await _card(db, meta, None, who)


@router.get("/api/project-templates/{template_id}")
async def get_template(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    meta, row, who = await _seen(db, template_id, user, request)
    return await _card(db, meta, row, who)


@router.get("/api/project-templates/{template_id}/detail")
async def get_template_detail(template_id: str, request: Request,
                              user: PlatformUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Everything the detail view and the reviewer read: the card, what the
    definition holds, and — for its builder and Tentoro's admins — the checks
    and each step of the review."""
    meta, row, who = await _seen(db, template_id, user, request)
    out = await _card(db, meta, row, who)
    try:
        out["preview"] = templates.preview(templates.load_definition(template_id))
    except (templates.TemplateError, ValueError, OSError):
        out["preview"] = None
    if out["can_manage"] or who.is_admin:
        out["checks"] = gallery.checks(meta)
        out["history"] = await gallery.history(db, template_id) if row else []
    mine = (await db.execute(select(TemplateReview).where(
        TemplateReview.lineage == templates.lineage_of(meta),
        TemplateReview.user_id == user.id))).scalar_one_or_none()
    out["my_review"] = ({"rating": int(mine.rating), "comment": mine.comment or ""} if mine else None)
    out["is_admin"] = who.is_admin
    return out


@router.patch("/api/project-templates/{template_id}")
async def update_template(template_id: str, req: UpdateTemplateRequest, request: Request,
                          user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    meta, row, who = await _managed(db, template_id, user, request)
    _editable(row)
    try:
        meta = templates.update(template_id, name=req.name, description=req.description,
                                category=req.category)
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _card(db, meta, row, who)


@router.delete("/api/project-templates/{template_id}", status_code=204)
async def delete_template(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Gone from the organisation, the review queue and the Gallery. Projects
    already made from it keep their own copy; its uses and ratings stay with
    the app's other versions."""
    await _managed(db, template_id, user, request)
    await gallery.forget(db, template_id)
    await db.commit()
    templates.delete(template_id)


# --------------------------------------------------------------------------- #
# Screenshots
# --------------------------------------------------------------------------- #

@router.post("/api/project-templates/{template_id}/screenshots", status_code=201)
async def upload_screenshot(template_id: str, request: Request, file: UploadFile = File(...),
                            caption: str = Query(default="", max_length=200),
                            user: PlatformUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    _meta, row, _who = await _managed(db, template_id, user, request)
    _editable(row)
    data = await file.read(templates.SCREENSHOT_BYTES_MAX + 1)
    try:
        shot = templates.add_screenshot(template_id, data, caption=caption)
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {k: shot.get(k) for k in ("id", "caption", "width", "height", "source")}


@router.post("/api/project-templates/{template_id}/screenshots/from-app")
async def add_app_screenshots(template_id: str, request: Request,
                              user: PlatformUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Add the pictures the build took of the app's own pages."""
    meta, row, _who = await _managed(db, template_id, user, request)
    _editable(row)
    source = meta.get("source_project_id")
    if not source:
        raise HTTPException(status_code=409, detail="This template has no app to take pictures from.")
    try:
        project = await get_project_with_auth(uuid.UUID(str(source)), user, db)
    except (HTTPException, ValueError):
        raise HTTPException(status_code=409, detail="The app this template came from is no longer there.")
    from routers.blueprint_generate import _output_dir
    try:
        added = templates.add_app_screens(template_id, _output_dir(project))
    except templates.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"added": [{k: s.get(k) for k in ("id", "caption", "width", "height", "source")} for s in added],
            "available": len(templates.app_screens(_output_dir(project)))}


@router.put("/api/project-templates/{template_id}/screenshots/order")
async def order_screenshots(template_id: str, req: OrderRequest, request: Request,
                            user: PlatformUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    _meta, row, _who = await _managed(db, template_id, user, request)
    _editable(row)
    shots = templates.order_screenshots(template_id, req.order)
    return {"screenshots": [{k: s.get(k) for k in ("id", "caption", "width", "height", "source")}
                            for s in shots]}


@router.patch("/api/project-templates/{template_id}/screenshots/{shot_id}")
async def caption_screenshot(template_id: str, shot_id: str, req: CaptionRequest, request: Request,
                             user: PlatformUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Say what a screenshot shows — the words under it in the Gallery."""
    _meta, row, _who = await _managed(db, template_id, user, request)
    _editable(row)
    shot = templates.caption_screenshot(template_id, shot_id, req.caption)
    if shot is None:
        raise HTTPException(status_code=404, detail="No such screenshot")
    return {k: shot.get(k) for k in ("id", "caption", "width", "height", "source")}


@router.delete("/api/project-templates/{template_id}/screenshots/{shot_id}", status_code=204)
async def delete_screenshot(template_id: str, shot_id: str, request: Request,
                            user: PlatformUser = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    _meta, row, _who = await _managed(db, template_id, user, request)
    _editable(row)
    if not templates.remove_screenshot(template_id, shot_id):
        raise HTTPException(status_code=404, detail="No such screenshot")


@router.get("/api/project-templates/{template_id}/screenshots/{shot_id}")
async def read_screenshot(template_id: str, shot_id: str, request: Request,
                          user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    await _seen(db, template_id, user, request)
    found = templates.screenshot_file(template_id, shot_id)
    if not found:
        raise HTTPException(status_code=404, detail="No such screenshot")
    path, media = found
    return FileResponse(str(path), media_type=media, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #

@router.get("/api/project-templates/{template_id}/checks")
async def template_checks(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    meta, _row, who = await _seen(db, template_id, user, request)
    if not (gallery.may_manage(meta, who) or who.is_admin):
        raise HTTPException(status_code=403, detail="Only its builder or Tentoro can see its checks")
    results = gallery.checks(meta)
    return {"checks": results, "ready": not gallery.blocking_failures(results)}


@router.post("/api/project-templates/{template_id}/submit")
async def submit_template(template_id: str, req: SubmitRequest, request: Request,
                          background: BackgroundTasks, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Send it to Tentoro for review — refused, naming what is missing, when a
    check that must pass does not."""
    meta, _row, who = await _seen(db, template_id, user, request)
    try:
        row, _results, outbox = await gallery.submit(
            db, meta, who, pricing_model=req.pricing_model, price_cents=req.price_cents,
            currency=req.currency, origin=_origin(request))
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    background.add_task(outbox.send)
    return await _card(db, meta, row, who)


@router.post("/api/project-templates/{template_id}/cancel-request")
async def cancel_request(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    meta, _row, who = await _seen(db, template_id, user, request)
    try:
        row = await gallery.cancel(db, meta, who)
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return await _card(db, meta, row, who)


@router.post("/api/project-templates/{template_id}/unpublish")
async def unpublish_template(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    meta, _row, who = await _seen(db, template_id, user, request)
    try:
        row = await gallery.unpublish(db, meta, who)
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return await _card(db, meta, row, who)


@router.get("/api/admin/template-requests/count")
async def count_template_requests(admin: PlatformUser = Depends(require_super_admin),
                                  db: AsyncSession = Depends(get_db)):
    """How many requests are waiting — the badge on the cockpit's Templates."""
    return {"pending": (await _counts(db))[gallery.PENDING]}


async def _counts(db: AsyncSession) -> dict[str, int]:
    """Listings per status — of templates that still exist. A row whose files
    are gone is not shown in the queue, so it is not counted either: the
    badge must never say one is waiting when the queue shows none."""
    counts = {st: 0 for st in gallery.STATUSES}
    for template_id, st in (await db.execute(
            select(TemplateListing.template_id, TemplateListing.status))).all():
        if st in counts and templates.get(template_id) is not None:
            counts[st] += 1
    return counts


@router.get("/api/admin/template-requests")
async def list_template_requests(request: Request, status: str = Query(default="pending"),
                                 admin: PlatformUser = Depends(require_super_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Tentoro's review queue — waiting requests first, oldest first, so the
    one that has waited longest is at the top."""
    query = select(TemplateListing)
    if status != "all":
        if status not in gallery.STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status")
        query = query.where(TemplateListing.status == status)
    rows = (await db.execute(query.order_by(TemplateListing.submitted_at.asc().nullslast()))).scalars().all()
    pairs = [(m, r) for r in rows if (m := templates.get(r.template_id))]
    return {"requests": await _cards(db, pairs, _viewer_factory(db, admin, request)),
            "counts": await _counts(db)}


@router.post("/api/admin/template-requests/{template_id}/decision")
async def decide_template_request(template_id: str, req: DecisionRequest, request: Request,
                                  background: BackgroundTasks,
                                  admin: PlatformUser = Depends(require_super_admin),
                                  db: AsyncSession = Depends(get_db)):
    meta = templates.get(template_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row, outbox = await gallery.decide(db, meta, admin, req.decision, req.note, origin=_origin(request))
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    background.add_task(outbox.send)
    who = await gallery.viewer(db, meta, admin, request.state)
    return await _card(db, meta, row, who)


@router.post("/api/admin/template-reviews/{review_id}/remove")
async def remove_template_review(review_id: uuid.UUID, req: ModerationRequest,
                                 admin: PlatformUser = Depends(require_super_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Tentoro takes a review down, saying why; its writer is told."""
    try:
        gone = await gallery.moderate(db, review_id, admin, req.reason)
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return {"removed": gone["id"]}


# --------------------------------------------------------------------------- #
# The Gallery
# --------------------------------------------------------------------------- #

@router.get("/api/template-gallery")
async def template_gallery(request: Request, search: str = Query(default="", max_length=120),
                           category: str = Query(default="", max_length=60),
                           sort: str = Query(default="popular", pattern="^(popular|rating|newest)$"),
                           user: PlatformUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    pairs = await gallery.published(db)
    cards = await _cards(db, pairs, _viewer_factory(db, user, request))
    categories = sorted({c["category"] for c in cards if c["category"]}, key=str.lower)
    q = search.strip().lower()
    if q:
        cards = [c for c in cards if q in " ".join(str(c.get(k) or "") for k in (
            "name", "description", "category", "created_by_name", "org_name")).lower()]
    if category:
        cards = [c for c in cards if c["category"].lower() == category.lower()]
    newest = lambda c: c.get("published_at") or ""
    if sort == "newest":
        cards.sort(key=newest, reverse=True)
    elif sort == "rating":
        cards.sort(key=lambda c: (c["rating"] or 0, c["ratings"], newest(c)), reverse=True)
    else:
        cards.sort(key=lambda c: (c["uses"], c["rating"] or 0, newest(c)), reverse=True)
    return {"templates": cards, "categories": categories}


@router.get("/api/project-templates/{template_id}/reviews")
async def list_reviews(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    meta, _row, _who = await _seen(db, template_id, user, request)
    return {"reviews": await gallery.reviews(db, templates.lineage_of(meta))}


@router.put("/api/project-templates/{template_id}/reviews/mine")
async def rate_template(template_id: str, req: RateRequest, request: Request,
                        user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    meta, row, who = await _seen(db, template_id, user, request)
    try:
        _review, new = await gallery.rate(db, meta, row, who, req.rating, req.comment)
    except gallery.GalleryError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    card = await _card(db, meta, row, who)
    return {"new": new, "rating": card["rating"], "ratings": card["ratings"],
            "my_review": {"rating": req.rating, "comment": req.comment.strip()}}


@router.delete("/api/project-templates/{template_id}/reviews/mine", status_code=204)
async def unrate_template(template_id: str, request: Request, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    meta, _row, _who = await _seen(db, template_id, user, request)
    if not await gallery.unrate(db, meta, user):
        raise HTTPException(status_code=404, detail="You have not rated it")
    await db.commit()


@router.get("/api/template-creators/{user_id}")
async def template_creator(user_id: uuid.UUID, request: Request,
                           user: PlatformUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """A builder's profile, as the Gallery shows it: who they are and what
    they have published. Only for someone with a template in the Gallery — it
    is not a way to look anyone up."""
    builder = await db.get(PlatformUser, user_id)
    pairs = [(m, r) for m, r in await gallery.published(db) if str(m.get("created_by")) == str(user_id)]
    if builder is None or not pairs:
        raise HTTPException(status_code=404, detail="No such builder in the Gallery")
    cards = await _cards(db, pairs, _viewer_factory(db, user, request))
    cards.sort(key=lambda c: c.get("published_at") or "", reverse=True)
    rated = [c for c in cards if c["ratings"]]
    total_ratings = sum(c["ratings"] for c in rated)
    return {
        "id": str(builder.id), "name": builder.name or builder.email.split("@")[0],
        "avatar_url": builder.avatar_url or None,
        "member_since": builder.created_at.isoformat() if builder.created_at else None,
        "organisations": sorted({c["org_name"] for c in cards if c["org_name"]}),
        "templates": cards,
        "totals": {"templates": len(cards), "uses": sum(c["uses"] for c in cards),
                   "ratings": total_ratings,
                   "rating": (round(sum(c["rating"] * c["ratings"] for c in rated) / total_ratings, 1)
                              if total_ratings else None)},
    }


# --------------------------------------------------------------------------- #
# Using one
# --------------------------------------------------------------------------- #

@router.post("/api/orgs/{org_id}/projects/from-project-template", response_model=ProjectResponse,
             status_code=201)
async def create_from_project_template(org_id: uuid.UUID, req: UseTemplateRequest, request: Request,
                                       user: PlatformUser = Depends(get_current_user),
                                       db: AsyncSession = Depends(get_db)):
    """A new project, with the template staged in it. Nothing is defined yet:
    the project's Smith asks whether the person wants the exact same app or
    one like it, and uses the template accordingly.

    Any template the person may see can be used: their own organisation's in
    any state, and everyone's in the Gallery. A Tentoro admin's copy of one
    under review is a test copy — kept, never counted as a use."""
    if not await gallery.membership(db, str(org_id), user):
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    meta = templates.get(req.template_id)
    row = await gallery.listing(db, req.template_id) if meta else None
    who = await gallery.viewer(db, meta, user, request.state) if meta else None
    if not meta or who is None or not gallery.may_use(gallery.status_of(row), who):
        raise HTTPException(status_code=404, detail="Template not found")
    is_review = who.is_admin and not who.in_org and gallery.status_of(row) != gallery.APPROVED
    project = await create_project(org_id=org_id, owner_id=user.id, name=req.name.strip(),
                                   description=meta.get("description") or "", db=db)
    from routers.blueprint_generate import _output_dir
    try:
        templates.stage(req.template_id, _output_dir(project))
    except templates.TemplateError as exc:
        await db.rollback()
        import shutil
        shutil.rmtree(_output_dir(project), ignore_errors=True)  # no orphan folder
        raise HTTPException(status_code=400, detail=str(exc))
    project.brief = {**(project.brief or {}),
                     "template": {"id": meta["id"], "name": meta["name"],
                                  "version": int(meta.get("version") or 1)}}
    await gallery.record_use(db, meta, project_id=project.id, user=user, org_id=org_id,
                             is_review=is_review)
    await db.commit()
    await db.refresh(project)
    return project


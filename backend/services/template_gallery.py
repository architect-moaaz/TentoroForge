"""The Templates Gallery: a template is reviewed by Tentoro before everyone can use it.

THE JOURNEY. A person saves a template of their app (`services.project_templates`
— a private draft their own organisation can already use), adds screenshots and
submits it. Every Tentoro admin (`platform_admin`, `admin@tentoro.ai` by default)
is told, in Forge and by email. An admin looks at it — its screens, records,
processes, screenshots and the checks below, and can open a test copy of it —
then approves it or asks for changes, with a reason. Approved, it is in the
Gallery for every organisation; its builder is told either way, and can follow
each step in the template's history.

WHAT IS WHERE. What a template IS stays on disk with it; what happens TO it —
the review, the projects made from it, the ratings — is in the database
(`models.template_gallery`), keyed by the template id. A template with no
listing row is a draft: one saved before the Gallery existed, or by Smith from
a chat turn, gets its row when it is first submitted.

VERSIONS. Saving a template of the same app again makes the next version of
one *lineage*. The Gallery shows the newest approved version; approving a newer
one retires the older (``superseded``). Uses and ratings belong to the lineage,
so a new version keeps what the old one earned.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import SUPER_ADMIN, PlatformUser
from models.org import InviteStatus, Organization, OrgMember, OrgMemberRole
from models.template_gallery import (
    TemplateEvent,
    TemplateListing,
    TemplateReview,
    TemplateUse,
)
from services import project_templates as templates

logger = logging.getLogger(__name__)

DRAFT = "draft"
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REMOVED = "removed"
SUPERSEDED = "superseded"
STATUSES = (DRAFT, PENDING, APPROVED, REJECTED, REMOVED, SUPERSEDED)

#: Where a submission may come from: a draft, a request changes were asked
#: for, or a template taken out of the Gallery. Submitting again while it is
#: already waiting or published is refused.
SUBMITTABLE = (DRAFT, REJECTED, REMOVED)
#: While these, the builder may still change what the reviewer will read.
#: Once approved it is what the Gallery shows: a change is a new version.
EDITABLE = (DRAFT, PENDING, REJECTED, REMOVED)

DESCRIPTION_MIN = 30
NOTE_MAX = 2000
COMMENT_MAX = 2000
PRICE_CENTS_MAX = 100_000_00
CURRENCIES = ("USD", "EUR", "GBP", "INR", "AED", "SAR")

#: Shapes of a live credential. A template is published to every organisation,
#: so a key left in its definition (a pasted token in a description, a hard-
#: coded one in one of Smith's file edits) would be published with it.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an Anthropic or OpenAI key", re.compile(r"\bsk-(?:ant-|proj-|live-)?[A-Za-z0-9_\-]{20,}")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("a Stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
)


class GalleryError(ValueError):
    """A step that cannot be taken — the message says why, `status` how to answer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Who is asking
# --------------------------------------------------------------------------- #

@dataclass
class Viewer:
    """The person asking, as far as one template is concerned."""

    user: PlatformUser
    member: OrgMember | None = None  # of the template's organisation
    is_admin: bool = False

    @property
    def in_org(self) -> bool:
        return self.member is not None

    @property
    def is_org_admin(self) -> bool:
        """An owner or admin of the template's organisation."""
        return self.member is not None and self.member.role in (OrgMemberRole.owner, OrgMemberRole.admin)


def is_admin(user: PlatformUser, request_state: Any = None) -> bool:
    """A Tentoro admin in their own right — never under an impersonation."""
    if request_state is not None and getattr(request_state, "impersonated_by", None):
        return False
    return bool(user is not None and user.platform_role == SUPER_ADMIN)


async def membership(db: AsyncSession, org_id: Any, user: PlatformUser) -> OrgMember | None:
    org_uuid = _uuid(org_id)
    if org_uuid is None:
        return None
    return (await db.execute(select(OrgMember).where(
        OrgMember.org_id == org_uuid, OrgMember.user_id == user.id,
        OrgMember.invite_status == InviteStatus.accepted))).scalar_one_or_none()


async def viewer(db: AsyncSession, meta: dict, user: PlatformUser, request_state: Any = None) -> Viewer:
    return Viewer(user=user, member=await membership(db, meta.get("org_id"), user),
                  is_admin=is_admin(user, request_state))


def may_manage(meta: dict, who: Viewer) -> bool:
    """Its builder, or an owner or admin of its organisation."""
    return who.in_org and (str(meta.get("created_by")) == str(who.user.id) or who.is_org_admin)


def may_view(status: str, who: Viewer) -> bool:
    """Its own organisation sees it in any state; Tentoro admins see every
    one; everyone else sees it only once it is in the Gallery."""
    return who.in_org or who.is_admin or status == APPROVED


def may_use(status: str, who: Viewer) -> bool:
    return may_view(status, who)


# --------------------------------------------------------------------------- #
# Listings
# --------------------------------------------------------------------------- #

async def listing(db: AsyncSession, template_id: str) -> TemplateListing | None:
    return await db.get(TemplateListing, template_id)


async def listings(db: AsyncSession, template_ids: list[str]) -> dict[str, TemplateListing]:
    if not template_ids:
        return {}
    rows = (await db.execute(select(TemplateListing).where(
        TemplateListing.template_id.in_(template_ids)))).scalars().all()
    return {r.template_id: r for r in rows}


def status_of(row: TemplateListing | None) -> str:
    return row.status if row is not None else DRAFT


async def _locked(db: AsyncSession, template_id: str) -> TemplateListing | None:
    """The listing, locked until this request commits, and read afresh.

    TWO PEOPLE AT ONCE. Every step reads the status, checks it may move, and
    writes the next one. Unlocked, six admins deciding one request at the
    same moment all read "pending" and all won — the history said rejected
    three times and approved three times, and the builder was sent six
    contradictory emails (found on Postgres, 2026-10-19). Locked, the second
    waits for the first, then reads what it decided and is refused.
    `populate_existing`: the request may already hold this row from an
    earlier unlocked read, which would otherwise be handed back unchanged."""
    return (await db.execute(
        select(TemplateListing).where(TemplateListing.template_id == template_id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def _lock_lineage(db: AsyncSession, lineage: str) -> None:
    """One app's versions are decided one request at a time. Row locks cover
    the rows that exist; two first submits of two versions each insert their
    own row, so both passed "one request per app". A transaction-scoped lock
    on the lineage itself closes that (Postgres; tests on SQLite run serially)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:l, 0))"), {"l": lineage})


async def _ensure_listing(db: AsyncSession, meta: dict) -> TemplateListing:
    """The template's listing, locked — made first if it has none. Two first
    submits at once both try to make it: the loser's insert is undone on its
    own (a savepoint) and it takes the winner's row, locked, like any step."""
    row = await _locked(db, meta["id"])
    if row is not None:
        return row
    try:
        async with db.begin_nested():
            db.add(TemplateListing(
                template_id=meta["id"], org_id=_uuid(meta["org_id"]),
                created_by=_uuid(meta.get("created_by")),
                source_project_id=_uuid(meta.get("source_project_id")),
                lineage=templates.lineage_of(meta), version=int(meta.get("version") or 1),
                status=DRAFT, pricing_model="free"))
    except IntegrityError:
        pass  # made by the request beside this one
    row = await _locked(db, meta["id"])
    assert row is not None
    return row


def _event(db: AsyncSession, template_id: str, status: str, actor: PlatformUser | None,
           note: str | None = None) -> None:
    # Stamped here, to the microsecond: the database's now() is the
    # transaction's start, so two steps of one decision (an approval and the
    # version it retires) would tie, and the history would read in any order.
    db.add(TemplateEvent(template_id=template_id, status=status, note=(note or None),
                         actor_id=actor.id if actor is not None else None, created_at=_now()))


async def history(db: AsyncSession, template_id: str) -> list[dict]:
    rows = (await db.execute(
        select(TemplateEvent, PlatformUser.name)
        .outerjoin(PlatformUser, PlatformUser.id == TemplateEvent.actor_id)
        .where(TemplateEvent.template_id == template_id)
        .order_by(TemplateEvent.created_at, TemplateEvent.id))).all()
    return [{"status": e.status, "note": e.note or "", "by": name or "",
             "at": e.created_at.isoformat() if e.created_at else None} for e, name in rows]


# --------------------------------------------------------------------------- #
# The checks a submission must pass
# --------------------------------------------------------------------------- #

def scan_secrets(template_id: str) -> list[str]:
    """Where in the template something shaped like a live credential sits —
    ``"the definition (an AWS access key)"`` — or nothing."""
    root = templates.templates_root() / template_id
    found = []
    for name, label in (("blueprint.json", "the definition"), (templates.PATCHES, "Smith's file edits"),
                        ("meta.json", "the name or description")):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        kinds = sorted({kind for kind, pattern in _SECRET_PATTERNS if pattern.search(text)})
        if kinds:
            found.append(f"{label} ({', '.join(kinds)})")
    return found


def checks(meta: dict) -> list[dict]:
    """What a reviewer needs to be true before they look, each said plainly.
    `blocking` ones refuse the submission; the others are told, not enforced."""
    out: list[dict] = []

    def check(key: str, ok: bool, label: str, detail: str = "", blocking: bool = True) -> None:
        out.append({"key": key, "ok": bool(ok), "label": label, "detail": detail if not ok else "",
                    "blocking": blocking})

    try:
        doc = templates.load_definition(meta["id"])
        loads = True
    except (templates.TemplateError, ValueError, OSError):  # missing, unreadable or not JSON
        doc, loads = {}, False
    check("definition", loads, "The app's definition is complete and loads",
          "The saved definition could not be read — save the template again from the app.")
    facts = templates.summary(doc) if loads else {"counts": {}, "designed": False}
    counts = facts.get("counts") or {}
    check("screens", counts.get("pages", 0) > 0 and counts.get("entities", 0) > 0,
          "It has screens and the records they keep",
          "Finish the app's screens and data model with Smith first; a template of a "
          "requirements list is not something another team can use yet.")
    check("designed", bool(facts.get("designed")), "Every screen has been designed and built",
          "Some screens have never been built. A copy will build them, which takes longer "
          "and spends AI credit.", blocking=False)
    name = str(meta.get("name") or "").strip()
    check("name", len(name) >= 3, "It has a name", "Give it a name of at least 3 characters.")
    description = str(meta.get("description") or "").strip()
    check("description", len(description) >= DESCRIPTION_MIN,
          "It says what the app is for",
          f"Describe what the app does and who it is for, in at least {DESCRIPTION_MIN} characters.")
    shots = len(meta.get("screenshots") or [])
    check("screenshots", shots >= 1, "It has at least one screenshot",
          "Add a screenshot — upload one, or add the app's own screens.")
    leaks = scan_secrets(meta["id"])
    check("secrets", not leaks, "No keys or passwords are in it",
          "Something shaped like a live key is in " + "; ".join(leaks) +
          ". Remove it from the app, then save the template again.")
    return out


def blocking_failures(results: list[dict]) -> list[dict]:
    return [c for c in results if c["blocking"] and not c["ok"]]


# --------------------------------------------------------------------------- #
# Notifications — in Forge, and by email
# --------------------------------------------------------------------------- #

@dataclass
class Outbox:
    """Emails to send once the change they announce is committed — never
    before, so nobody is told about a decision that was then rolled back."""

    emails: list[tuple[str, str, dict]] = field(default_factory=list)

    async def send(self) -> None:
        # The builder's words are escaped where they are put into HTML
        # (`email_service.render`), not here: a subject is plain text.
        from services.email_service import send_email
        for to, template, context in self.emails:
            try:
                await send_email(to, template, context)
            except Exception:
                logger.exception("[gallery] could not email %s (%s)", to, template)


def app_url(path: str, origin: str = "") -> str:
    base = (os.environ.get("FORGE_APP_BASE_URL") or origin or "").rstrip("/")
    return f"{base}{path}"


def creator_link(meta: dict) -> str:
    return f"/org/{meta.get('org_id')}/templates?template={meta.get('id')}"


def admin_link(meta: dict) -> str:
    return f"/admin/templates?request={meta.get('id')}"


async def _notify(db: AsyncSession, user_ids: list[uuid.UUID], kind: str, title: str, content: str,
                  link: str, meta: dict) -> None:
    from services.notification_service import NotificationService
    svc = NotificationService(db)
    for uid in dict.fromkeys(user_ids):
        await svc.create(uid, kind, title[:255], content, link=link[:500],
                         metadata={"template_id": meta.get("id"), "template_name": meta.get("name")})


async def admins(db: AsyncSession) -> tuple[list[PlatformUser], set[str]]:
    """Every Tentoro admin who has an account, and every address to email —
    the configured admin emails (`admin@tentoro.ai`) even before they sign up."""
    from platform_admin import super_admin_emails
    emails = super_admin_emails()
    users = (await db.execute(select(PlatformUser).where(
        PlatformUser.disabled_at.is_(None),
        or_(PlatformUser.platform_role == SUPER_ADMIN,
            func.lower(PlatformUser.email).in_(sorted(emails) or [""]))))).scalars().all()
    # A configured address whose login was disabled is not written to either.
    disabled = {e.lower() for e in (await db.execute(select(PlatformUser.email).where(
        PlatformUser.disabled_at.is_not(None),
        func.lower(PlatformUser.email).in_(sorted(emails) or [""])))).scalars().all()}
    return list(users), (emails - disabled) | {u.email.lower() for u in users}


# --------------------------------------------------------------------------- #
# The steps
# --------------------------------------------------------------------------- #

def _check_pricing(model: str, price_cents: int | None,
                   currency: str | None) -> tuple[str, int | None, str | None]:
    model = (model or "free").strip().lower()
    if model == "free":
        return "free", None, None
    if model != "paid":
        raise GalleryError("A template is free or paid.")
    # Kept ready for paid templates; nothing can be charged for yet.
    raise GalleryError("Paid templates are coming soon — submit it as free for now.")


async def submit(db: AsyncSession, meta: dict, who: Viewer, *, pricing_model: str = "free",
                 price_cents: int | None = None, currency: str | None = None,
                 origin: str = "") -> tuple[TemplateListing, list[dict], Outbox]:
    """Send the template to Tentoro for review. Refused, with the checks, when
    a blocking one fails."""
    if not may_manage(meta, who):
        raise GalleryError("Only the template's builder or an admin of its organisation can submit it.", 403)
    # Every version of the app, locked in the order a decision locks them, so
    # a submit and a decision on two versions never wait on each other.
    await _lock_lineage(db, templates.lineage_of(meta))
    lineage_rows = (await db.execute(
        select(TemplateListing).where(TemplateListing.lineage == templates.lineage_of(meta))
        .order_by(TemplateListing.template_id)
        .with_for_update().execution_options(populate_existing=True))).scalars().all()
    row = await _ensure_listing(db, meta)
    if row.status not in SUBMITTABLE:
        raise GalleryError({PENDING: "It is already waiting for review.",
                            APPROVED: "It is already in the Gallery. Save a new version of the app "
                                      "to send a change for review.",
                            SUPERSEDED: "A newer version of it is in the Gallery."}
                           .get(row.status, "It cannot be submitted now."), 409)
    # ONE REQUEST PER APP. An older version cannot be sent while a newer one
    # waits or is live (approving it would change nothing); a newer one takes
    # the place of an older request still waiting.
    others = [r for r in lineage_rows if r.template_id != row.template_id]
    newer = sorted((r for r in others if r.version > row.version and r.status in (PENDING, APPROVED)),
                   key=lambda r: -r.version)
    if newer:
        n = newer[0]
        raise GalleryError(f"Version {n.version} of it is {'waiting for review' if n.status == PENDING else 'in the Gallery'} "
                           f"already — this is an older version (v{row.version}). Send the newest one instead.", 409)
    model, cents, cur = _check_pricing(pricing_model, price_cents, currency)
    results = checks(meta)
    failed = blocking_failures(results)
    if failed:
        raise GalleryError("It is not ready to submit: " + " ".join(c["detail"] for c in failed), 422)
    for old in (r for r in others if r.version < row.version and r.status == PENDING):
        old.status, old.review_note = DRAFT, None
        _event(db, old.template_id, DRAFT, who.user, f"Replaced in the review queue by version {row.version}")
    row.status, row.pricing_model, row.price_cents, row.currency = PENDING, model, cents, cur
    row.submitted_at, row.submitted_by, row.review_note = _now(), who.user.id, None
    resubmitted = await db.scalar(select(func.count()).select_from(TemplateEvent).where(
        TemplateEvent.template_id == row.template_id, TemplateEvent.status == PENDING))
    _event(db, row.template_id, PENDING, who.user, "Sent again for review" if resubmitted else None)

    outbox = Outbox()
    admin_users, emails = await admins(db)
    who_name = who.user.name or who.user.email
    org = await db.get(Organization, _uuid(meta["org_id"]))
    org_name = org.name if org else ""
    title = f"Template to review: {meta.get('name')}"
    content = (f"{who_name}{f' ({org_name})' if org_name else ''} asked for “{meta.get('name')}” "
               f"(v{row.version}) to be added to the Templates Gallery.")
    await _notify(db, [u.id for u in admin_users], "template_review_requested", title, content,
                  admin_link(meta), meta)
    if not emails:
        # Nobody to tell: the request is kept and is in the queue, but no
        # admin will hear of it until one looks. Said loudly, not silently.
        logger.error("[gallery] %s was submitted but no Tentoro admin is configured "
                     "(FORGE_SUPER_ADMIN_EMAILS is empty and nobody holds the role)", meta.get("id"))
    for email in sorted(emails):
        outbox.emails.append((email, "template_review_requested", {
            "template_name": meta.get("name"), "requester": who_name, "org_name": org_name or "—",
            "version": row.version, "description": str(meta.get("description") or "")[:400],
            "review_url": app_url(admin_link(meta), origin)}))
    return row, results, outbox


async def cancel(db: AsyncSession, meta: dict, who: Viewer) -> TemplateListing:
    """Take back a request that has not been decided."""
    if not may_manage(meta, who):
        raise GalleryError("Only the template's builder or an admin of its organisation can do that.", 403)
    row = await _locked(db, meta["id"])
    if row is None or row.status != PENDING:
        raise GalleryError("There is no request waiting for review to take back.", 409)
    row.status = DRAFT
    _event(db, row.template_id, DRAFT, who.user, "Request taken back")
    return row


async def unpublish(db: AsyncSession, meta: dict, who: Viewer) -> TemplateListing:
    """The builder takes their template out of the Gallery."""
    if not may_manage(meta, who):
        raise GalleryError("Only the template's builder or an admin of its organisation can do that.", 403)
    row = await _locked(db, meta["id"])
    if row is None or row.status != APPROVED:
        raise GalleryError("It is not in the Gallery.", 409)
    row.status = REMOVED
    _event(db, row.template_id, REMOVED, who.user, "Taken out of the Gallery by its builder")
    return row


async def decide(db: AsyncSession, meta: dict, admin: PlatformUser, decision: str, note: str = "",
                 origin: str = "") -> tuple[TemplateListing, Outbox]:
    """A Tentoro admin's decision: ``approve``, ``reject`` (ask for changes)
    or ``remove`` (take an approved one out of the Gallery)."""
    note = str(note or "").strip()[:NOTE_MAX]
    # Every version of this app is locked, always in the same order: approving
    # v3 retires v2, so two admins approving v2 and v3 at once must not each
    # see the other still pending (both would stay in the Gallery) — and
    # locking only one's own row first would let them wait on each other.
    await _lock_lineage(db, templates.lineage_of(meta))
    lineage_rows = (await db.execute(
        select(TemplateListing).where(TemplateListing.lineage == templates.lineage_of(meta))
        .order_by(TemplateListing.template_id)
        .with_for_update().execution_options(populate_existing=True))).scalars().all()
    row = next((r for r in lineage_rows if r.template_id == meta["id"]), None)
    status = status_of(row)
    if decision == "approve":
        if status != PENDING:
            raise GalleryError("Only a template waiting for review can be approved.", 409)
        failed = blocking_failures(checks(meta))
        if failed:
            raise GalleryError("It no longer passes its checks: " +
                               " ".join(c["detail"] for c in failed), 422)
        new_status = APPROVED
    elif decision == "reject":
        if status != PENDING:
            raise GalleryError("Only a template waiting for review can be sent back.", 409)
        if not note:
            raise GalleryError("Say what needs to change — the builder reads it.")
        new_status = REJECTED
    elif decision == "remove":
        if status != APPROVED:
            raise GalleryError("Only a template in the Gallery can be taken out of it.", 409)
        if not note:
            raise GalleryError("Say why it is being taken out — the builder reads it.")
        new_status = REMOVED
    else:
        raise GalleryError("Unknown decision.")
    assert row is not None
    now = _now()
    row.status, row.reviewed_at, row.reviewed_by, row.review_note = new_status, now, admin.id, note or None
    if new_status == APPROVED:
        row.published_at = now
        # The newest approved version is the one in the Gallery.
        older = [r for r in lineage_rows
                 if r.status == APPROVED and r.template_id != row.template_id]
        for old in older:
            if old.version < row.version:
                old.status = SUPERSEDED
                _event(db, old.template_id, SUPERSEDED, admin, f"Replaced by version {row.version}")
            else:  # an older version approved after a newer one: it stays out
                row.status = SUPERSEDED
    _event(db, row.template_id, row.status, admin, note)

    outbox = Outbox()
    # Told: whoever asked for this review, and the template's builder — one
    # person when they are the same, two when an organisation's admin
    # submitted a colleague's template. A disabled login is not written to.
    told = []
    for uid in dict.fromkeys(u for u in (row.submitted_by, row.created_by) if u):
        person = await db.get(PlatformUser, uid)
        if person is not None and person.disabled_at is None:
            told.append(person)
    words = {APPROVED: ("is in the Templates Gallery", "template_approved"),
             SUPERSEDED: ("was approved, but a newer version is already in the Gallery",
                          "template_approved"),
             REJECTED: ("needs changes before it can be published", "template_changes_requested"),
             REMOVED: ("was taken out of the Templates Gallery", "template_removed")}[row.status]
    if told:
        await _notify(db, [p.id for p in told], words[1], f"“{meta.get('name')}” {words[0]}",
                      note or "Tentoro reviewed your template.", creator_link(meta), meta)
    for person in told:
        outbox.emails.append((person.email, words[1], {
            "name": person.name or "there", "template_name": meta.get("name"),
            "note": note or "—", "template_url": app_url(creator_link(meta), origin)}))
    return row, outbox


async def record_use(db: AsyncSession, meta: dict, *, project_id: uuid.UUID, user: PlatformUser,
                     org_id: uuid.UUID, is_review: bool) -> None:
    db.add(TemplateUse(template_id=meta["id"], lineage=templates.lineage_of(meta),
                       project_id=project_id, user_id=user.id, org_id=org_id, is_review=is_review))


# --------------------------------------------------------------------------- #
# What the Gallery counts
# --------------------------------------------------------------------------- #

async def stats(db: AsyncSession, lineages: list[str]) -> dict[str, dict]:
    """Uses (an admin's test copies are not uses) and ratings, per lineage."""
    out = {ln: {"uses": 0, "rating": None, "ratings": 0} for ln in lineages}
    if not lineages:
        return out
    for ln, n in (await db.execute(
            select(TemplateUse.lineage, func.count()).where(
                TemplateUse.lineage.in_(lineages), TemplateUse.is_review.is_(False))
            .group_by(TemplateUse.lineage))).all():
        out[ln]["uses"] = int(n)
    for ln, avg, n in (await db.execute(
            select(TemplateReview.lineage, func.avg(TemplateReview.rating), func.count())
            .where(TemplateReview.lineage.in_(lineages)).group_by(TemplateReview.lineage))).all():
        out[ln]["rating"] = round(float(avg), 1) if avg is not None else None
        out[ln]["ratings"] = int(n)
    return out


async def published(db: AsyncSession) -> list[tuple[dict, TemplateListing]]:
    """The Gallery: the newest approved version of every lineage."""
    rows = (await db.execute(select(TemplateListing).where(
        TemplateListing.status == APPROVED))).scalars().all()
    newest: dict[str, TemplateListing] = {}
    for r in rows:
        if r.lineage not in newest or r.version > newest[r.lineage].version:
            newest[r.lineage] = r
    out = []
    for r in newest.values():
        meta = templates.get(r.template_id)
        if meta:  # a template deleted from disk is not shown, whatever its row says
            out.append((meta, r))
    return out


async def people(db: AsyncSession, user_ids: list[Any]) -> dict[str, dict]:
    ids = [u for u in (_uuid(x) for x in user_ids) if u is not None]
    if not ids:
        return {}
    rows = (await db.execute(select(PlatformUser).where(PlatformUser.id.in_(ids)))).scalars().all()
    return {str(u.id): {"id": str(u.id), "name": u.name or u.email.split("@")[0],
                        "avatar_url": u.avatar_url or None} for u in rows}


async def org_names(db: AsyncSession, org_ids: list[Any]) -> dict[str, str]:
    ids = [o for o in (_uuid(x) for x in org_ids) if o is not None]
    if not ids:
        return {}
    rows = (await db.execute(select(Organization.id, Organization.name).where(
        Organization.id.in_(ids)))).all()
    return {str(i): n for i, n in rows}


# --------------------------------------------------------------------------- #
# Ratings and feedback
# --------------------------------------------------------------------------- #

async def reviews(db: AsyncSession, lineage: str, *, limit: int = 100) -> list[dict]:
    rows = (await db.execute(
        select(TemplateReview, PlatformUser)
        .join(PlatformUser, PlatformUser.id == TemplateReview.user_id)
        .where(TemplateReview.lineage == lineage)
        .order_by(TemplateReview.updated_at.desc(), TemplateReview.id).limit(limit))).all()
    used = set()
    if rows:
        used = {str(u) for u in (await db.execute(select(TemplateUse.user_id).where(
            TemplateUse.lineage == lineage, TemplateUse.is_review.is_(False),
            TemplateUse.user_id.in_([r.user_id for r, _ in rows])))).scalars().all()}
    return [{"id": str(r.id), "user": {"id": str(u.id), "name": u.name or u.email.split("@")[0],
                                       "avatar_url": u.avatar_url or None},
             "rating": int(r.rating), "comment": r.comment or "", "used_it": str(u.id) in used,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r, u in rows]


def may_rate(meta: dict, status: str, who: Viewer) -> bool:
    """Anyone signed in may rate a template in the Gallery — except the
    organisation that made it: its builder and their colleagues would be
    marking their own work, and the stars are for people choosing one. Nor
    Tentoro's admins: they judge what is in the Gallery, so they do not score it."""
    return (status == APPROVED and not who.in_org and not who.is_admin
            and str(meta.get("created_by")) != str(who.user.id))


async def rate(db: AsyncSession, meta: dict, row: TemplateListing | None, who: Viewer,
               rating: Any, comment: str = "") -> tuple[TemplateReview, bool]:
    """Set this person's rating of the template. Returns it and whether it is new."""
    user = who.user
    if status_of(row) != APPROVED:
        raise GalleryError("Only a template in the Gallery can be rated.", 409)
    if str(meta.get("created_by")) == str(user.id):
        raise GalleryError("You cannot rate your own template.", 403)
    if who.in_org:
        raise GalleryError("Your organisation built this template, so its rating is for others to give.", 403)
    if who.is_admin:
        raise GalleryError("Tentoro's admins decide what is in the Gallery, so they do not rate it.", 403)
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise GalleryError("A rating is a whole number of stars from 1 to 5.")
    comment = str(comment or "").strip()
    if len(comment) > COMMENT_MAX:
        raise GalleryError(f"Feedback can be at most {COMMENT_MAX} characters.")
    lineage = templates.lineage_of(meta)

    async def own_review() -> TemplateReview | None:
        return (await db.execute(
            select(TemplateReview).where(TemplateReview.lineage == lineage,
                                         TemplateReview.user_id == user.id)
            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()

    mine = await own_review()
    new = False
    if mine is None:
        # A double-clicked "Post review": both find none and both insert. The
        # second insert is undone on its own and becomes an edit of the first,
        # instead of a 500 at commit.
        try:
            async with db.begin_nested():
                db.add(TemplateReview(lineage=lineage, template_id=meta["id"], user_id=user.id,
                                      rating=rating, comment=comment or None))
            new = True
        except IntegrityError:
            pass
        mine = await own_review()
        assert mine is not None
    if not new:
        mine.rating, mine.comment, mine.template_id = rating, comment or None, meta["id"]
        mine.updated_at = _now()
    if new and meta.get("created_by") and _uuid(meta.get("created_by")):
        stars = "★" * rating + "☆" * (5 - rating)
        await _notify(db, [_uuid(meta["created_by"])], "template_rated",
                      f"New rating for “{meta.get('name')}”: {stars}",
                      f"{user.name or 'Someone'}: {comment[:300]}" if comment else
                      f"{user.name or 'Someone'} rated it {rating} of 5.",
                      creator_link(meta), meta)
    return mine, new


async def unrate(db: AsyncSession, meta: dict, user: PlatformUser) -> bool:
    mine = (await db.execute(select(TemplateReview).where(
        TemplateReview.lineage == templates.lineage_of(meta),
        TemplateReview.user_id == user.id))).scalar_one_or_none()
    if mine is None:
        return False
    await db.delete(mine)
    return True


async def moderate(db: AsyncSession, review_id: Any, admin: PlatformUser, reason: str) -> dict:
    """Tentoro takes a review down — abusive, off-topic, or not about the
    template. The reason is required, the reviewer is told it, and the
    removal is on the audit record. Returns what was removed."""
    reason = str(reason or "").strip()[:NOTE_MAX]
    if not reason:
        raise GalleryError("Say why the review is being removed — its writer is told.")
    rid = _uuid(review_id)
    review = (await db.execute(select(TemplateReview).where(TemplateReview.id == rid)
                               .with_for_update())).scalar_one_or_none() if rid else None
    if review is None:
        raise GalleryError("That review does not exist.", 404)
    meta = templates.get(review.template_id) or {"id": review.template_id, "name": "a template"}
    gone = {"id": str(review.id), "template_id": review.template_id, "user_id": str(review.user_id),
            "rating": int(review.rating), "comment": review.comment or ""}
    await db.delete(review)
    from services.audit_service import audit_log
    await audit_log(db, admin.id, "template_review.removed", "template_review", gone["id"],
                    changes={**gone, "reason": reason}, actor_user_id=admin.id)
    await _notify(db, [review.user_id], "template_review_removed",
                  f"Your review of “{meta.get('name')}” was removed",
                  f"Tentoro removed it: {reason}", "", meta)
    return gone


async def forget(db: AsyncSession, template_id: str) -> None:
    """A deleted template leaves the review queue and the Gallery. Its uses
    and ratings stay with the lineage: a newer version keeps them."""
    row = await listing(db, template_id)
    if row is not None:
        await db.delete(row)


__all__ = [
    "APPROVED", "DRAFT", "EDITABLE", "PENDING", "REJECTED", "REMOVED", "STATUSES", "SUBMITTABLE",
    "SUPERSEDED", "GalleryError", "Outbox", "Viewer", "admins", "blocking_failures", "cancel",
    "checks", "decide", "forget", "moderate", "history", "is_admin", "listing", "listings", "may_manage", "may_rate",
    "may_use", "may_view", "membership", "org_names", "people", "published", "rate", "record_use",
    "reviews", "scan_secrets", "stats", "status_of", "submit", "unpublish", "unrate", "viewer",
]

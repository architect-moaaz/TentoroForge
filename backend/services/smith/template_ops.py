"""Templates, from the chat: what state this app's templates are in, and
sending one to Tentoro for review — the same calls the Templates page makes
(`services.project_templates`, `services.template_gallery`).

A Smith turn runs on a worker thread with no database session of its own, so
the review step opens its own short-lived connection (no pool to leak), runs
the gallery's own `submit` — every check, the admins told — and closes it.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

#: A status in the words the Templates page uses.
STATUS_SAID = {
    "draft": "private — only your organisation can use it",
    "pending": "waiting for Tentoro's review",
    "approved": "in the Templates Gallery — everyone can use it",
    "rejected": "sent back by Tentoro with changes to make",
    "removed": "taken out of the Gallery by Tentoro",
    "superseded": "replaced by a newer version",
}


def _rows(template_ids: list[str]) -> dict[str, dict]:
    """Each template's listing (status, version, price, the reviewer's note)."""
    if not template_ids:
        return {}
    from sqlalchemy import text

    from services.project_templates import _sync_engine
    try:
        with _sync_engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT template_id, status, version, pricing_model, price_cents, currency, review_note "
                "FROM template_listings WHERE template_id = ANY(:ids)"), {"ids": template_ids}).mappings().all()
    except Exception:  # noqa: BLE001 — no listing read: every template reads as private
        logger.exception("[smith-templates] could not read the listings")
        return {}
    return {str(r["template_id"]): dict(r) for r in rows}


def _uses(lineages: list[str]) -> dict[str, int]:
    if not lineages:
        return {}
    from sqlalchemy import text

    from services.project_templates import _sync_engine
    try:
        with _sync_engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT lineage, count(*) FROM template_uses WHERE lineage = ANY(:l) GROUP BY lineage"),
                {"l": lineages}).all()
    except Exception:  # noqa: BLE001 — the count is a nicety
        return {}
    return {str(r[0]): int(r[1]) for r in rows}


def mine(project_id: str) -> list[dict]:
    """This organisation's templates, this app's first, each with its status."""
    from services import project_templates as templates
    facts = templates.project_facts(str(project_id))
    if not facts:
        return []
    metas = templates.list_for_org(facts["org_id"])
    rows = _rows([str(m.get("id")) for m in metas])
    uses = _uses(sorted({templates.lineage_of(m) for m in metas}))
    out = []
    for m in metas:
        r = rows.get(str(m.get("id"))) or {}
        out.append({"id": m.get("id"), "name": m.get("name"), "version": int(m.get("version") or 1),
                    "lineage": templates.lineage_of(m),
                    "fromThisApp": str(m.get("source_project_id") or "") == str(project_id),
                    "status": str(r.get("status") or "draft"), "note": r.get("review_note") or "",
                    "screenshots": len(m.get("screenshots") or []),
                    "uses": uses.get(templates.lineage_of(m), 0),
                    "price": (f"{(r.get('price_cents') or 0) / 100:.2f} {r.get('currency') or ''}".strip()
                              if r.get("pricing_model") == "paid" else "free")})
    out.sort(key=lambda t: (not t["fromThisApp"], -t["version"]))
    return out


def status_said(project_id: str, org_id: str) -> str:
    """The answer to "is my template approved?", "what templates do we have?"."""
    items = mine(project_id)
    if not items:
        return ("This app has no template yet, and neither does your organisation. Say “save this app as a "
                "template” and I will make one.")
    # ONE LINE PER TEMPLATE: its newest version, and the version in the
    # Gallery when that is an older one (each save is a new version).
    by_lineage: dict[str, list[dict]] = {}
    for t in items:
        by_lineage.setdefault(t["lineage"], []).append(t)
    lines = []
    for versions in by_lineage.values():
        versions.sort(key=lambda t: -t["version"])
        t = versions[0]
        line = (f"- “{t['name']}” (version {t['version']}{', from this app' if t['fromThisApp'] else ''}): "
                f"{STATUS_SAID.get(t['status'], t['status'])}")
        live = next((v for v in versions[1:] if v["status"] == "approved"), None)
        if live and t["status"] != "approved":
            line += f"; version {live['version']} is in the Templates Gallery"
        if t["status"] == "rejected" and t["note"]:
            line += f" — Tentoro said: “{t['note']}”"
        if t["uses"]:
            line += f"; used {t['uses']} time{'s' if t['uses'] != 1 else ''}"
        lines.append(line)
    return ("Your organisation's templates:\n" + "\n".join(lines)
            + f"\n\nSee and manage them in [Templates](/org/{org_id}/templates).")


async def _submit(template_id: str, user_id: str, *, pricing_model: str, price_cents: int | None,
                  currency: str | None) -> tuple[Any, list[dict]]:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from config import DATABASE_URL
    from models.auth import PlatformUser
    from services import project_templates as templates
    from services import template_gallery as gallery
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            user = await db.get(PlatformUser, uuid.UUID(user_id))
            if user is None:
                raise gallery.GalleryError("I could not tell who is sending it.", 403)
            meta = templates.get(template_id)
            if meta is None:
                raise gallery.GalleryError("That template is no longer there.", 404)
            who = await gallery.viewer(db, meta, user)
            try:
                row, results, outbox = await gallery.submit(db, meta, who, pricing_model=pricing_model,
                                                             price_cents=price_cents, currency=currency)
            except Exception:
                await db.rollback()
                raise
            await db.commit()
        try:
            await outbox.send()
        except Exception:  # noqa: BLE001 — sent for review; a missed email is not a failed submit
            logger.exception("[smith-templates] telling the reviewers failed")
        return row, results
    finally:
        await engine.dispose()


def submit(output_dir: str, project_id: str, *, name: str = "", pricing_model: str = "free",
           price_cents: int | None = None, currency: str | None = None) -> str:
    """Send this app's newest template (or the one named) for review: the app's
    own page pictures added first when it has none. The answer, in words."""
    from services import project_templates as templates
    from services import template_gallery as gallery
    facts = templates.project_facts(str(project_id))
    if not facts:
        return "I could not find which organisation this app belongs to, so nothing was sent."
    org = facts["org_id"]
    items = mine(project_id)
    want = name.strip().lower()
    pick = next((t for t in items if want and want in str(t["name"]).lower()), None) if want else None
    pick = pick or next((t for t in items if t["fromThisApp"] and t["status"] in ("draft", "rejected")), None)
    if pick is None:
        live = next((t for t in items if t["fromThisApp"]), None)
        if live and live["status"] in ("pending", "approved"):
            return (f"“{live['name']}” (version {live['version']}) is already "
                    f"{STATUS_SAID[live['status']]}. Nothing to send.")
        return ("This app has no template to send yet. Say “save this app as a template” first, "
                "then ask me to submit it.")
    added = []
    if not pick["screenshots"]:
        try:
            added = templates.add_app_screens(str(pick["id"]), output_dir)
        except Exception:  # noqa: BLE001 — said below
            logger.exception("[smith-templates] could not add the app's pictures")
    if not pick["screenshots"] and not added:
        return (f"“{pick['name']}” needs at least one picture before Tentoro can review it, and this app has none "
                f"I can add. Open [Templates](/org/{org}/templates?submit={pick['id']}), add a screenshot, and "
                "press Submit for review — or ask me again once the app has been built.")
    try:
        row, _results = asyncio.run(_submit(str(pick["id"]), facts["owner_id"], pricing_model=pricing_model,
                                            price_cents=price_cents, currency=currency))
    except gallery.GalleryError as exc:
        return f"Not sent: {exc}"
    pics = f" I added {len(added)} picture{'s' if len(added) != 1 else ''} of the app's own pages first." if added else ""
    return (f"Sent “{pick['name']}” (version {pick['version']}) to Tentoro for review, as a "
            f"{'free' if pricing_model == 'free' else 'paid'} template.{pics} You will get a notification when they "
            f"decide; until then it shows “Waiting for review” in [Templates](/org/{org}/templates), where you can "
            "also add more pictures, change the description or price, or cancel the request.")


__all__ = ["STATUS_SAID", "mine", "status_said", "submit"]

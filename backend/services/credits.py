"""The policy as the tables hold it, and the questions the cockpit asks of it.

`services.spending` is arithmetic over ledger rows and a policy mapping;
this is where the mapping comes from — `credit_entries` and `spend_limits`
(`models.credits`) — and where the cockpit writes to it. Every number
leaves here as a float; `Decimal` stays at the boundary.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import PlatformUser
from models.credits import CREDIT_KINDS, CreditEntry, SpendLimit
from models.org import Organization
from models.project import Project
from services import spending


def _f(value: Any) -> float:
    return float(value) if isinstance(value, Decimal) else float(value or 0.0)


def _epoch(moment: datetime | None) -> float:
    if moment is None:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

async def projects_known(db: AsyncSession) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Every application by short id — its organisation, owner and name —
    and the names the check speaks in (`org:<id>` → name, `project:<id>` → name)."""
    rows = (await db.execute(select(Project.short_id, Project.name, Project.org_id, Project.owner_id))).all()
    owners = {r.owner_id for r in rows if r.owner_id is not None}
    emails: dict[str, str] = {}
    if owners:
        found = (await db.execute(select(PlatformUser.id, PlatformUser.email)
                                  .where(PlatformUser.id.in_(list(owners))))).all()
        emails = {str(u.id): u.email for u in found}
    orgs = (await db.execute(select(Organization.id, Organization.name))).all()
    projects = {str(r.short_id): {"org": str(r.org_id), "owner": emails.get(str(r.owner_id), ""), "name": r.name}
                for r in rows}
    names = {f"org:{o.id}": o.name for o in orgs}
    # WHOSE A DELETED APPLICATION WAS. The register keeps every application
    # this has ever listed; one no longer in the table keeps its spend with
    # its organisation and owner (services/app_register).
    from services import app_register
    app_register.remember(projects)
    for app_id, info in app_register.all_apps().items():
        if app_id not in projects:
            projects[app_id] = {"org": info.get("org", ""), "owner": info.get("owner", ""),
                                "name": info.get("name", "") or app_id, "deleted": True}
    names.update({f"project:{k}": v["name"] for k, v in projects.items()})
    return projects, names


def _entry(e: CreditEntry, by_email: str = "") -> dict[str, Any]:
    return {"id": str(e.id), "org_id": str(e.org_id), "at": _epoch(e.at), "at_iso": e.at.isoformat() if e.at else None,
            "amount": _f(e.amount_usd), "kind": e.kind, "note": e.note, "by": str(e.by_user_id or ""),
            "by_email": by_email}


async def load_policy(db: AsyncSession) -> dict[str, Any]:
    """The whole policy: credit entries per organisation, limits per scope."""
    entries = (await db.execute(select(CreditEntry).order_by(CreditEntry.at))).scalars().all()
    credits: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        credits.setdefault(str(e.org_id), []).append(_entry(e))
    limits: dict[str, dict[str, float]] = {}
    for row in (await db.execute(select(SpendLimit))).scalars().all():
        key = spending.scope_key(**{row.scope_kind: row.scope_id}) if row.scope_kind != "platform" else spending.PLATFORM
        limits.setdefault(key, {})[row.period] = _f(row.amount_usd)
    return {"credits": credits, "limits": limits}


async def entries_of(db: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """An organisation's credit history, newest first, with who made each entry."""
    rows = (await db.execute(
        select(CreditEntry, PlatformUser.email).outerjoin(PlatformUser, PlatformUser.id == CreditEntry.by_user_id)
        .where(CreditEntry.org_id == org_id).order_by(CreditEntry.at.desc())
    )).all()
    return [_entry(e, email or "") for e, email in rows]


async def limits_for(db: AsyncSession, scope_kind: str, scope_id: str = "") -> dict[str, float]:
    rows = (await db.execute(select(SpendLimit).where(
        SpendLimit.scope_kind == scope_kind, SpendLimit.scope_id == (scope_id or "")))).scalars().all()
    return {r.period: _f(r.amount_usd) for r in rows}


async def all_limits(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(SpendLimit).order_by(SpendLimit.scope_kind, SpendLimit.scope_id, SpendLimit.period))).scalars().all()
    return [{"scope_kind": r.scope_kind, "scope_id": r.scope_id, "period": r.period, "amount_usd": _f(r.amount_usd),
             "set_by": str(r.set_by or ""), "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows]


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

async def add_entry(db: AsyncSession, org_id: uuid.UUID, amount_usd: float, kind: str, note: str,
                    by_user_id: uuid.UUID | None) -> dict[str, Any]:
    """A signed credit entry. `opening` and `top_up` put money on; `adjustment`
    goes either way; `refund` takes it off. The first entry of an organisation
    is its opening balance — recorded as `opening` once; after that a top-up."""
    if kind not in CREDIT_KINDS:
        raise ValueError(f"not a kind of entry: {kind!r}")
    amount = round(float(amount_usd), 4)
    if amount == 0:
        raise ValueError("an entry is an amount, not zero")
    if kind in ("opening", "top_up") and amount < 0:
        raise ValueError(f"a {kind.replace('_', '-')} is a positive amount")
    if kind == "refund" and amount > 0:
        raise ValueError("a refund takes money off: a negative amount")
    if len((note or "").strip()) < 3:
        raise ValueError("say why: a note of at least 3 characters")
    existing = (await db.execute(select(CreditEntry.id).where(CreditEntry.org_id == org_id).limit(1))).first()
    if kind == "opening" and existing is not None:
        raise ValueError("the organisation already has an opening balance; add a top-up")
    entry = CreditEntry(org_id=org_id, amount_usd=amount, kind=kind, note=note.strip(), by_user_id=by_user_id,
                        at=datetime.now(timezone.utc))
    db.add(entry)
    await db.flush()
    return _entry(entry)


async def set_limits(db: AsyncSession, scope_kind: str, scope_id: str, periods: Mapping[str, Any],
                     set_by: uuid.UUID | None) -> dict[str, float]:
    """Limits for one scope per period, as `spending.clean_limits` reads
    them: a period left out, empty or zero loses its row. Returns what the
    scope now has."""
    if scope_kind not in spending.SCOPE_KINDS:
        raise ValueError(f"not a scope: {scope_kind!r}")
    scope_id = "" if scope_kind == "platform" else str(scope_id or "").strip()
    if scope_kind != "platform" and not scope_id:
        raise ValueError(f"a {scope_kind} limit names the {scope_kind}")
    clean = spending.clean_limits(periods)
    await db.execute(delete(SpendLimit).where(SpendLimit.scope_kind == scope_kind, SpendLimit.scope_id == scope_id,
                                              SpendLimit.period.not_in(list(clean)) if clean else True))
    for period, amount in clean.items():
        row = (await db.execute(select(SpendLimit).where(
            SpendLimit.scope_kind == scope_kind, SpendLimit.scope_id == scope_id, SpendLimit.period == period
        ))).scalar_one_or_none()
        if row is None:
            db.add(SpendLimit(scope_kind=scope_kind, scope_id=scope_id, period=period, amount_usd=amount, set_by=set_by))
        else:
            row.amount_usd = amount
            row.set_by = set_by
    await db.flush()
    return clean


# --------------------------------------------------------------------------- #
# Standing
# --------------------------------------------------------------------------- #

async def org_standing(db: AsyncSession, rows: Iterable[Mapping[str, Any]], org_id: uuid.UUID,
                       policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """An organisation's balance and where it stands against its limits."""
    policy = policy or await load_policy(db)
    projects, _ = await projects_known(db)
    rows = list(rows)
    out = spending.standing(rows, org=str(org_id), policy=policy, projects=projects)
    out["limits_set"] = (policy.get("limits") or {}).get(f"org:{org_id}") or {}
    out["platform_limits"] = (policy.get("limits") or {}).get(spending.PLATFORM) or {}
    out["build_estimate_usd"] = spending.estimate_build_usd(spending.attributed(rows, projects), org=str(org_id))
    return out


async def all_org_balances(db: AsyncSession, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every organisation with its credit, spend and balance — the cockpit's table."""
    policy = await load_policy(db)
    projects, _ = await projects_known(db)
    attributed = spending.attributed(list(rows), projects)
    orgs = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    out = []
    for org in orgs:
        bal = spending.balance(attributed, policy, org=str(org.id))
        entries = (policy.get("credits") or {}).get(str(org.id)) or []
        spent_total = sum(float(r["cost_usd"]) for r in attributed if r.get("org") == str(org.id))
        out.append({
            "org_id": str(org.id), "name": org.name, "slug": org.slug, "status": org.status,
            **bal, "spent_all_time_usd": round(spent_total, 4),
            "entries": len(entries), "last_entry": entries[-1] if entries else None,
            "limits": (policy.get("limits") or {}).get(f"org:{org.id}") or {},
        })
    return out


# --------------------------------------------------------------------------- #
# The door
# --------------------------------------------------------------------------- #

async def refusal(db: AsyncSession, *, org_id: Any, user_email: str, project_short_id: str,
                  estimate: float | None = None, turn: bool = False) -> list[str]:
    """Why work must not start for this organisation, person and app, in the
    administrator's words — empty when it may. `estimate` defaults to a
    build's expected cost (the organisation's recent builds, else the
    platform's, else the default), or a turn's when `turn`."""
    from services.build_usage import read_ledger

    rows = read_ledger()
    policy = await load_policy(db)
    projects, names = await projects_known(db)
    if estimate is None:
        estimate = spending.TURN_USD if turn else spending.estimate_build_usd(
            spending.attributed(rows, projects), org=str(org_id or ""))
    return spending.check(rows, estimate=float(estimate), org=str(org_id or ""), user=str(user_email or ""),
                          project=str(project_short_id or ""), policy=policy, projects=projects, names=names)


async def gate(db: AsyncSession, *, org_id: Any, user_email: str, project_short_id: str = "",
               estimate: float | None = None, turn: bool = False) -> None:
    """NOTHING STARTS THAT THE ORGANISATION CANNOT PAY FOR. A five-module
    build sank $14 before the API refused it for an empty balance (forge-v3,
    2026-10-10). Raises 402 with the reasons; the check itself failing lets
    the work through — the record of it is a warning, never a refusal."""
    import logging

    from fastapi import HTTPException

    try:
        why = await refusal(db, org_id=org_id, user_email=user_email, project_short_id=project_short_id,
                            estimate=estimate, turn=turn)
    except Exception:  # noqa: BLE001 — the check never breaks the work it guards
        logging.getLogger(__name__).warning("[spend] the check before work could not run", exc_info=True)
        return
    if why:
        raise HTTPException(status_code=402, detail="Not started: " + "; ".join(why) + ".")


__all__ = ["projects_known", "load_policy", "entries_of", "limits_for", "all_limits", "add_entry", "set_limits",
           "org_standing", "all_org_balances", "refusal", "gate"]

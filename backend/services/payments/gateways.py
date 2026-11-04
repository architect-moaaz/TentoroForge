"""An organisation's payment gateways: saved, checked, shown, chosen.

The keys of each mode are one JSON object sealed with the platform's
integrations key under a subkey of their own (`payment_gateway:<id>:<mode>`),
so a row's test keys and live keys never share a key, and one row's keys
cannot be opened as another's. Nothing here returns a key: the page sees its
last four characters, an app's environment sees the value (`env_for`), and
only when the app chose this gateway.

Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.payment_gateway import PaymentGateway
from services.payments import providers as P
from services.platform_integrations_crypto import CryptoError, decrypt, encrypt

logger = logging.getLogger(__name__)

LABEL_MAX = 80
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class GatewayError(ValueError):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _subkey(gateway_id: Any, mode: str) -> str:
    return f"payment_gateway:{gateway_id}:{mode}"


def seal(gateway_id: Any, mode: str, keys: dict[str, str]) -> tuple[str, str]:
    try:
        return encrypt(_subkey(gateway_id, mode), json.dumps(keys, sort_keys=True))
    except CryptoError as exc:
        raise GatewayError(str(exc), status=500) from exc


def keys_of(row: PaymentGateway, mode: str) -> dict[str, str]:
    """The decrypted keys of one mode, or {} when it is not set (or cannot be
    opened — logged, never raised: a corrupted row is a gateway not set)."""
    ct, iv = (row.test_ct, row.test_iv) if mode == P.TEST else (row.live_ct, row.live_iv)
    if not ct or not iv:
        return {}
    try:
        data = json.loads(decrypt(_subkey(row.id, mode), ct, iv))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (CryptoError, ValueError) as exc:
        logger.warning("[payments] gateway %s %s keys unreadable: %s", row.id, mode, exc)
        return {}


def has_mode(row: PaymentGateway, mode: str) -> bool:
    return bool(row.test_ct if mode == P.TEST else row.live_ct)


def status_of(row: PaymentGateway) -> str:
    """ready (live keys checked) · test_only (only test keys, checked) ·
    unchecked (keys saved, never confirmed) · attention (a check failed)."""
    checks = row.checks or {}
    live, test = checks.get(P.LIVE) or {}, checks.get(P.TEST) or {}
    if has_mode(row, P.LIVE):
        if live.get("ok"):
            return "ready"
        return "attention" if live.get("reachable", True) and live.get("error") else "unchecked"
    if has_mode(row, P.TEST):
        if test.get("ok"):
            return "test_only"
        return "attention" if test.get("reachable", True) and test.get("error") else "unchecked"
    return "attention"


def view(row: PaymentGateway, *, admin: bool) -> dict[str, Any]:
    """A gateway as the pages show it. Masked keys only for an admin."""
    p = P.PROVIDERS.get(row.provider)
    modes: dict[str, Any] = {}
    for mode in P.MODES:
        set_ = has_mode(row, mode)
        entry: dict[str, Any] = {"set": set_, "check": _public_check((row.checks or {}).get(mode))}
        if admin and set_:
            keys = keys_of(row, mode)
            entry["masked"] = {k: (P.mask(v) if any(f.key == k and f.secret for f in (p.fields if p else ())) else
                                   (v[:6] + "…" + v[-4:] if len(v) > 14 else v)) for k, v in keys.items()}
        modes[mode] = entry
    return {
        "id": str(row.id), "provider": row.provider, "providerName": p.name if p else row.provider,
        "label": row.label, "coverage": row.coverage, "homeCountry": row.home_country,
        "currencies": list(row.currencies or []), "isDefault": bool(row.is_default),
        "status": status_of(row), "modes": modes,
        "webhooks": p.webhooks if p else "manual", "testName": p.test_name if p else "Test mode",
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _public_check(check: Any) -> dict[str, Any] | None:
    if not isinstance(check, dict):
        return None
    return {k: check.get(k) for k in ("ok", "reachable", "account", "accountId", "country", "currency", "checkedAt", "error")
            if k in check}


async def listing(db: AsyncSession, org_id: Any) -> list[PaymentGateway]:
    rows = (await db.execute(select(PaymentGateway).where(
        PaymentGateway.org_id == org_id, PaymentGateway.deleted_at.is_(None)
    ).order_by(PaymentGateway.is_default.desc(), PaymentGateway.created_at))).scalars().all()
    return list(rows)


async def get(db: AsyncSession, org_id: Any, gateway_id: Any, *, with_deleted: bool = False) -> PaymentGateway:
    try:
        gid = uuid.UUID(str(gateway_id))
    except (TypeError, ValueError):
        raise GatewayError("No such gateway.", status=404) from None
    row = await db.get(PaymentGateway, gid)
    if row is None or str(row.org_id) != str(org_id) or (row.deleted_at is not None and not with_deleted):
        raise GatewayError("No such gateway.", status=404)
    return row


def _clean_label(label: Any, provider: P.Provider) -> str:
    text = re.sub(r"[\x00-\x1f\x7f​-‏‪-‮⁠-⁤﻿]", "", str(label or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > LABEL_MAX:
        raise GatewayError(f"A gateway's name is at most {LABEL_MAX} characters.")
    return text or provider.name


def _clean_coverage(coverage: Any, provider: P.Provider) -> str:
    c = str(coverage or provider.coverage).strip().lower()
    if c not in P.COVERAGES:
        raise GatewayError("Who it takes money from is domestic, international or both.")
    return c


def _clean_country(country: Any, coverage: str, provider: P.Provider) -> str | None:
    c = str(country or "").strip().upper() or (provider.home_country or "")
    if not c:
        if coverage == "domestic":
            raise GatewayError("A domestic gateway needs its home country (for example IN for India).")
        return None
    if not _COUNTRY.match(c):
        raise GatewayError("The home country is a two-letter code, like IN or AE.")
    return c


def _clean_currencies(currencies: Any, provider: P.Provider) -> list[str]:
    raw = currencies if isinstance(currencies, list) else list(provider.default_currencies)
    out: list[str] = []
    for c in raw:
        code = str(c or "").strip().upper()
        if not code:
            continue
        if code not in provider.currencies:
            raise GatewayError(f"{provider.name} does not take payments in {code} here. "
                               f"It can: {', '.join(provider.currencies)}.")
        if code not in out:
            out.append(code)
    if not out:
        raise GatewayError("Choose at least one currency it takes payments in.")
    return out


async def _check_and_seal(row: PaymentGateway, provider: P.Provider, mode: str, keys: dict[str, str]) -> None:
    """Verify one mode's keys; refuse keys the gateway refused; seal the rest."""
    found = await P.verify(provider.id, mode, keys)
    if not found.get("ok") and found.get("reachable"):
        raise GatewayError(found.get("error") or f"{provider.name} refused these keys.")
    ct, iv = seal(row.id, mode, keys)
    if mode == P.TEST:
        row.test_ct, row.test_iv = ct, iv
    else:
        row.live_ct, row.live_iv = ct, iv
    checks = dict(row.checks or {})
    checks[mode] = {k: v for k, v in found.items() if k != "mode"}
    row.checks = checks


async def _make_default(db: AsyncSession, row: PaymentGateway) -> None:
    await db.execute(update(PaymentGateway).where(
        PaymentGateway.org_id == row.org_id, PaymentGateway.id != row.id).values(is_default=False))
    row.is_default = True


async def create(db: AsyncSession, org_id: Any, user_id: Any, body: dict[str, Any]) -> PaymentGateway:
    try:
        provider = P.provider(body.get("provider"))
        test = P.clean_keys(provider.id, P.TEST, body.get("test"))
        live = P.clean_keys(provider.id, P.LIVE, body.get("live"))
    except P.KeyProblem as exc:
        raise GatewayError(str(exc)) from exc
    if not test and not live:
        raise GatewayError(f"Add {provider.name}'s {provider.test_name.lower()} keys, its live keys, or both.")
    coverage = _clean_coverage(body.get("coverage"), provider)
    row = PaymentGateway(
        id=uuid.uuid4(), org_id=org_id, provider=provider.id, label=_clean_label(body.get("label"), provider),
        coverage=coverage, home_country=_clean_country(body.get("homeCountry"), coverage, provider),
        currencies=_clean_currencies(body.get("currencies"), provider), is_default=False, checks={},
        created_by=user_id, updated_by=user_id)
    for mode, keys in ((P.TEST, test), (P.LIVE, live)):
        if keys:
            await _check_and_seal(row, provider, mode, keys)
    others = await listing(db, org_id)
    db.add(row)
    await db.flush()
    if body.get("isDefault") or not others:
        await _make_default(db, row)
    return row


async def edit(db: AsyncSession, row: PaymentGateway, user_id: Any, body: dict[str, Any]) -> PaymentGateway:
    provider = P.provider(row.provider)
    if "label" in body:
        row.label = _clean_label(body.get("label"), provider)
    if "coverage" in body or "homeCountry" in body:
        coverage = _clean_coverage(body.get("coverage", row.coverage), provider)
        row.coverage = coverage
        row.home_country = _clean_country(body.get("homeCountry", row.home_country), coverage, provider)
    if "currencies" in body:
        row.currencies = _clean_currencies(body.get("currencies"), provider)
    for mode in P.MODES:
        if mode in (body.get("clear") or []):
            if mode == P.TEST:
                row.test_ct = row.test_iv = None
            else:
                row.live_ct = row.live_iv = None
            checks = dict(row.checks or {})
            checks.pop(mode, None)
            row.checks = checks
            continue
        sent = body.get(mode)
        if not isinstance(sent, dict) or not any(str(v or "").strip() for v in sent.values()):
            continue
        # A field left empty keeps what is stored: re-typing a secret to fix a
        # typo in the id is not asked of anyone.
        merged = {**keys_of(row, mode), **{k: v for k, v in sent.items() if str(v or "").strip()}}
        try:
            keys = P.clean_keys(provider.id, mode, merged)
        except P.KeyProblem as exc:
            raise GatewayError(str(exc)) from exc
        await _check_and_seal(row, provider, mode, keys)
    if not has_mode(row, P.TEST) and not has_mode(row, P.LIVE):
        raise GatewayError("A gateway keeps at least one set of keys. Remove the gateway instead.")
    if body.get("isDefault") is True:
        await _make_default(db, row)
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    return row


async def recheck(row: PaymentGateway) -> PaymentGateway:
    """Check every mode that has keys again; record what was found (never refuse)."""
    checks = dict(row.checks or {})
    for mode in P.MODES:
        keys = keys_of(row, mode)
        if keys:
            found = await P.verify(row.provider, mode, keys)
            checks[mode] = {k: v for k, v in found.items() if k != "mode"}
    row.checks = checks
    row.updated_at = datetime.now(timezone.utc)
    return row


async def remove(db: AsyncSession, row: PaymentGateway) -> None:
    row.deleted_at = datetime.now(timezone.utc)
    was_default = row.is_default
    row.is_default = False
    row.test_ct = row.test_iv = row.live_ct = row.live_iv = None
    await db.flush()
    if was_default:
        rest = await listing(db, row.org_id)
        if rest:
            await _make_default(db, rest[0])


def apps_using(project_dirs: list[tuple[str, str, str]], gateway_id: str) -> list[dict[str, str]]:
    """The applications (id, name) whose Blueprint chose this gateway.
    `project_dirs`: (project id, name, output dir)."""
    out = []
    for pid, name, out_dir in project_dirs:
        try:
            doc = json.loads((Path(out_dir) / ".forge" / "blueprint" / "current.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        chosen = ((doc.get("payments") or {}).get("gateways") or []) if isinstance(doc, dict) else []
        if any(isinstance(g, dict) and str(g.get("gateway")) == str(gateway_id) for g in chosen):
            out.append({"id": pid, "name": name})
    return out


__all__ = ["GatewayError", "apps_using", "create", "edit", "get", "has_mode", "keys_of", "listing", "recheck",
           "remove", "seal", "status_of", "view"]

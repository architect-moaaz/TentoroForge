"""Each application's webhook at each gateway, for each side — and the keys a
side's environment gets.

Stripe and PayPal let Forge register the app's webhook itself: at publish,
`ensure_webhooks` creates the endpoint once (Stripe answers with its signing
secret, PayPal with the webhook id its verification needs), keeps it in
`payment_gateway_webhooks` (encrypted) and reuses it on every later publish,
moving it when the app's address changed. Razorpay lets only its partners
register webhooks by API, so Forge makes the secret, keeps it, and the app's
Payments panel shows the owner the address, the secret and the events to
paste once into Razorpay's dashboard. Until a webhook arrives, a payment is
still confirmed when the payer returns (`/api/pay/return`, `/api/pay/confirm`).

Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
"""
from __future__ import annotations

import json
import logging
import secrets as _secrets
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.payment_gateway import PaymentGateway, PaymentGatewayWebhook
from services.payments import app_payments as AP
from services.payments import providers as P
from services.payments.gateways import keys_of
from services.platform_integrations_crypto import CryptoError, decrypt, encrypt

logger = logging.getLogger(__name__)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20.0)


def _seal(row_id: Any, value: str) -> tuple[str, str]:
    return encrypt(f"payment_webhook:{row_id}", value)


def _open(row: PaymentGatewayWebhook) -> str:
    if not row.secret_ct or not row.secret_iv:
        return ""
    try:
        return decrypt(f"payment_webhook:{row.id}", row.secret_ct, row.secret_iv)
    except CryptoError:
        logger.warning("[payments] webhook secret %s unreadable", row.id)
        return ""


def load_doc(output_dir: str | Path) -> dict | None:
    try:
        return json.loads((Path(output_dir) / ".forge" / "blueprint" / "current.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def governs(doc: dict | None) -> bool:
    """Do this app's payments come from Settings → Integrations → Payments? (An app built
    before that keeps the Stripe keys it had, untouched — even once Forge has
    recorded a decision of its own for it: see `relies_on_older_stripe`.)"""
    return bool(doc) and AP.section(doc).get("decidedBy") is not None and not AP.relies_on_older_stripe(doc)


async def _rows(db: AsyncSession, org_id: Any) -> list[PaymentGateway]:
    return list((await db.execute(select(PaymentGateway).where(PaymentGateway.org_id == org_id))).scalars().all())


async def payment_env(output_dir: str | Path, org_id: Any, db: AsyncSession, *, side: str,
                      webhooks: dict[str, str] | None = None) -> dict[str, str | None] | None:
    """The payment variables one side of this app gets (None: remove it), or
    None when the app's payments are not the gateways' to decide."""
    doc = load_doc(output_dir)
    if not governs(doc):
        return None
    return AP.env_for_side(doc, await _rows(db, org_id), side, webhooks=webhooks)


async def ensure_webhooks(db: AsyncSession, *, project_id: Any, output_dir: str | Path, org_id: Any, side: str,
                          address: str) -> dict[str, Any]:
    """Register (or reuse, or move) the app's webhook at each chosen gateway
    for one side. Never raises: a gateway that cannot be reached leaves its
    row `failed` with the reason, and the publish goes on.

    Returns ``{secrets: {provider: secret}, report: [{provider, status, url, detail}]}``."""
    doc = load_doc(output_dir)
    out: dict[str, Any] = {"secrets": {}, "report": []}
    if not governs(doc) or not AP.takes_money(doc) or not address:
        return out
    mode = P.LIVE if side == "production" else P.TEST
    # ONE PUBLISH AT A TIME REGISTERS THIS APP'S WEBHOOKS FOR A SIDE. Two at
    # once each made an endpoint; the second's row collided, its publish lost
    # its payment keys, and its endpoint was left at the gateway, failing every
    # signature. Held until this transaction commits (below).
    try:
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"forge-webhooks:{project_id}:{side}"})
    except Exception:  # noqa: BLE001 — no lock is the old behaviour, not a failed publish
        logger.warning("[payments] the webhook lock could not be taken", exc_info=True)
    by_id = {str(r.id): r for r in await _rows(db, org_id)}
    for g in AP.section(doc).get("gateways") or []:
        row = by_id.get(str(g.get("gateway")))
        if row is None or row.deleted_at is not None:
            continue
        keys = keys_of(row, mode)
        if not keys:
            out["report"].append({"provider": row.provider, "status": "skipped",
                                  "detail": f"no {'live' if mode == P.LIVE else 'test'} keys"})
            continue
        url = f"{address.rstrip('/')}/api/webhooks/{AP.integration_slug(row.provider)}"
        hook = (await db.execute(select(PaymentGatewayWebhook).where(
            PaymentGatewayWebhook.gateway_id == row.id, PaymentGatewayWebhook.project_id == project_id,
            PaymentGatewayWebhook.side == side))).scalar_one_or_none()
        if hook is None:
            hook = PaymentGatewayWebhook(id=uuid.uuid4(), gateway_id=row.id, project_id=project_id, side=side, url=url,
                                         status="manual")
            db.add(hook)
        try:
            if row.provider == "stripe":
                await _stripe(hook, keys, url)
            elif row.provider == "paypal":
                await _paypal(hook, keys, url, mode)
            else:
                if not _open(hook):
                    ct, iv = _seal(hook.id, _secrets.token_urlsafe(24))
                    hook.secret_ct, hook.secret_iv = ct, iv
                hook.url, hook.status, hook.detail = url, "manual", "Paste this address and secret into Razorpay once."
        except Exception as exc:  # noqa: BLE001 — a webhook is a second path; the return confirms payments
            logger.warning("[payments] %s webhook for %s/%s failed: %s", row.provider, project_id, side, exc)
            hook.status, hook.detail = "failed", str(exc)[:500]
        await db.flush()
        secret = _open(hook)
        if secret:
            out["secrets"][row.provider] = secret
        out["report"].append({"provider": row.provider, "status": hook.status, "url": hook.url, "detail": hook.detail})
    await db.commit()
    return out


async def _stripe(hook: PaymentGatewayWebhook, keys: dict[str, str], url: str) -> None:
    from services.payments.providers import _base
    base = _base("stripe", "")
    auth = {"Authorization": f"Bearer {keys['secret_key']}"}
    async with _client() as http:
        if hook.provider_ref and _open(hook):
            if hook.url == url and hook.status == "registered":
                return
            resp = await http.post(f"{base}/v1/webhook_endpoints/{hook.provider_ref}", headers=auth, data={"url": url})
            if resp.status_code == 200:
                hook.url, hook.status, hook.detail = url, "registered", "Moved to the app's current address."
                return
            # Gone at Stripe (deleted by hand, or the keys are another account's
            # now): make a new one. Anything else — busy, down — is tried at the
            # next publish: a new endpoint each time left orphans that count
            # toward Stripe's 16 and fail every signature.
            if resp.status_code != 404:
                raise RuntimeError(f"Stripe answered {resp.status_code} when the endpoint was moved; it is tried again at the next publish")
        form: list[tuple[str, str]] = [("url", url), ("description", "Forge app payments"), ("metadata[forge]", "1")]
        form += [("enabled_events[]", e) for e in AP.WEBHOOK_EVENTS["stripe"]]
        from urllib.parse import urlencode
        resp = await http.post(f"{base}/v1/webhook_endpoints", content=urlencode(form),
                               headers={**auth, "Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code != 200:
            raise RuntimeError(f"Stripe answered {resp.status_code}: {resp.json().get('error', {}).get('message', '')}")
        body = resp.json()
        ct, iv = _seal(hook.id, str(body["secret"]))
        hook.provider_ref, hook.secret_ct, hook.secret_iv = str(body["id"]), ct, iv
        hook.url, hook.status, hook.detail = url, "registered", "Registered with Stripe by Forge."


async def _paypal(hook: PaymentGatewayWebhook, keys: dict[str, str], url: str, mode: str) -> None:
    from services.payments.providers import _base, _basic
    base = _base("paypal", mode)
    async with _client() as http:
        tok = await http.post(f"{base}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                              headers={"Authorization": _basic(keys["client_id"], keys["client_secret"])})
        if tok.status_code != 200:
            raise RuntimeError(f"PayPal refused the keys ({tok.status_code})")
        auth = {"Authorization": f"Bearer {tok.json()['access_token']}", "Content-Type": "application/json"}
        if hook.provider_ref and hook.url == url and hook.status == "registered" and _open(hook):
            return
        events = [{"name": e} for e in AP.WEBHOOK_EVENTS["paypal"]]
        resp = await http.post(f"{base}/v1/notifications/webhooks", headers=auth, json={"url": url, "event_types": events})
        if resp.status_code in (200, 201):
            wid = str(resp.json()["id"])
        else:
            name = str((resp.json() or {}).get("name") or "")
            if name != "WEBHOOK_URL_ALREADY_EXISTS":
                raise RuntimeError(f"PayPal answered {resp.status_code}: {name or resp.text[:200]}")
            listed = await http.get(f"{base}/v1/notifications/webhooks", headers=auth)
            wid = next((str(w["id"]) for w in (listed.json() or {}).get("webhooks") or [] if w.get("url") == url), "")
            if not wid:
                raise RuntimeError("PayPal says the address is registered but does not list it")
        ct, iv = _seal(hook.id, wid)
        hook.provider_ref, hook.secret_ct, hook.secret_iv = wid, ct, iv
        hook.url, hook.status, hook.detail = url, "registered", "Registered with PayPal by Forge."


async def setup_for(db: AsyncSession, project_id: Any, *, admin: bool = True, doc: dict | None = None) -> list[dict[str, Any]]:
    """What the app's Payments panel shows about its webhooks: per gateway and
    side, the address, whether Forge registered it, and — for Razorpay, which
    the owner registers — the secret and events to paste.

    THE SIGNING SECRET IS AN ADMINISTRATOR'S. With it anyone can sign a
    "payment captured" the app believes; a member sees that it must be pasted,
    not what. `doc`: only the gateways the app takes money through now — a
    gateway it no longer uses has nothing left to paste."""
    rows = (await db.execute(select(PaymentGatewayWebhook, PaymentGateway).join(
        PaymentGateway, PaymentGateway.id == PaymentGatewayWebhook.gateway_id).where(
        PaymentGatewayWebhook.project_id == project_id))).all()
    chosen = None if doc is None else {str(g.get("gateway")) for g in AP.section(doc).get("gateways") or []}
    out = []
    for hook, gw in rows:
        if gw.deleted_at is not None or (chosen is not None and str(gw.id) not in chosen):
            continue
        manual = hook.status == "manual"
        entry = {"provider": gw.provider, "gateway": str(gw.id), "label": gw.label, "side": hook.side, "url": hook.url,
                 "status": hook.status, "detail": hook.detail}
        if manual:
            entry["events"] = AP.WEBHOOK_EVENTS.get(gw.provider, [])
            if admin:
                entry["secret"] = _open(hook)
            else:
                entry["secretHidden"] = True
        out.append(entry)
    return out


__all__ = ["ensure_webhooks", "governs", "load_doc", "payment_env", "setup_for"]

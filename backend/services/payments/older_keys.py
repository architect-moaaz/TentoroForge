"""The Stripe keys an organisation typed before payment gateways existed.

They sit under Integrations as six `STRIPE_*` values and still reach every
app whose payments predate gateways (`webhooks.governs` is false): those apps
read the variables straight from the environment. Payments now live in
Integrations too, as gateways, so the same Stripe account would otherwise be
set up twice with nothing joining the two.

Here: which older keys are set, which apps still rely on them, and the keys
sorted into a gateway's test and live slots — by what each key IS (its
`sk_test_` / `sk_live_` prefix), not by the slot it was typed into, since the
old form had test keys typed into `STRIPE_SECRET_KEY` as often as not.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.payments import providers as P

logger = logging.getLogger(__name__)

PROVIDER = "stripe"
#: The older names, the gateway field each fills, and the slot it was typed into.
NAMES: dict[str, tuple[str, str]] = {
    "STRIPE_SECRET_KEY": ("secret_key", P.LIVE),
    "STRIPE_PUBLISHABLE_KEY": ("publishable_key", P.LIVE),
    "STRIPE_TEST_SECRET_KEY": ("secret_key", P.TEST),
    "STRIPE_TEST_PUBLISHABLE_KEY": ("publishable_key", P.TEST),
}
#: Set with the keys, but a gateway registers its own webhook at publish.
WEBHOOK_NAMES = ("STRIPE_WEBHOOK_SECRET", "STRIPE_TEST_WEBHOOK_SECRET")


async def stored(db: AsyncSession, org_id: Any) -> dict[str, str]:
    """The older Stripe values that are set, by name (decrypted, server side only)."""
    from models.platform_integration import PlatformIntegration
    from services.platform_integrations_crypto import CryptoError, decrypt
    rows = (await db.execute(select(PlatformIntegration).where(
        PlatformIntegration.org_id == org_id, PlatformIntegration.provider == PROVIDER))).scalars().all()
    out: dict[str, str] = {}
    for r in rows:
        if not (r.value_ct and r.value_iv):
            continue
        try:
            out[r.key] = decrypt(PROVIDER, r.value_ct, r.value_iv)
        except CryptoError:
            logger.warning("[payments] an older Stripe value (%s) could not be opened", r.key)
    return out


def _mode_of(value: str, typed_as: str) -> str:
    for mode in P.MODES:
        if value.startswith(("sk_" + mode + "_", "rk_" + mode + "_", "pk_" + mode + "_")):
            return mode
    return typed_as


def sorted_keys(values: dict[str, str]) -> dict[str, dict[str, str]]:
    """The older keys as a gateway's `test` and `live` keys. A key typed into
    the other slot goes where it belongs; when two keys claim one slot, the one
    typed into that slot wins."""
    out: dict[str, dict[str, str]] = {P.TEST: {}, P.LIVE: {}}
    # Slot-matching keys last, so they win a clash.
    order = sorted(NAMES.items(), key=lambda kv: _mode_of(values.get(kv[0], ""), kv[1][1]) == kv[1][1])
    for name, (field, typed_as) in order:
        value = (values.get(name) or "").strip()
        if value:
            out[_mode_of(value, typed_as)][field] = value
    return out


def apps_relying(project_dirs: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """Apps whose payments predate gateways and that take money through Stripe:
    the ones the older keys still serve. `(id, name, output_dir)` each."""
    from services.payments import app_payments as AP
    from services.payments.webhooks import governs, load_doc
    out: list[dict[str, str]] = []
    for pid, name, out_dir in project_dirs:
        doc = load_doc(out_dir)
        if not doc or governs(doc):
            continue
        stripe = any(isinstance(r, dict) and str(r.get("provider") or "").lower() == PROVIDER
                     and str(r.get("status") or "").upper() not in AP._RETIRED
                     for r in doc.get("integrations") or [])
        if stripe:
            out.append({"id": pid, "name": name})
    return out


__all__ = ["NAMES", "PROVIDER", "WEBHOOK_NAMES", "apps_relying", "sorted_keys", "stored"]

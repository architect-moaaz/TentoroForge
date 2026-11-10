"""Smith sets up how an application takes money — through the organisation's
own gateways (Settings → Integrations → Payments), never a key typed into the chat.

"Take payments through Razorpay", "add a Pro plan at 499 rupees a month",
"let people subscribe yearly", "members must subscribe to use it", "stop
taking payments". What the person named is applied; what they did not name
is kept as it was (or, for a new setup, the organisation's best gateways for
the app's currency). When nothing names a gateway and the organisation has
several, Smith does not guess: it answers with the chip that opens the
gateway dialog. With no gateway connected at all, it says where to connect
one — and the app works meanwhile with the stand-in, which charges nobody.

Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

VERB = "set_up_payments"

_OFF = re.compile(r"\b(?:stop|turn\s+off|switch\s+off|remove|disable|no\s+longer|don'?t|do\s+not)\b[^.]*\b(?:payments?|charging|charge|subscriptions?|billing)\b"
                  r"|\b(?:make\s+it|keep\s+it)\s+free\b", re.I)
_SUB = re.compile(r"\b(?:subscri\w*|members?hip|plans?|monthly|yearly|annual(?:ly)?|per\s+(?:month|year)|a\s+(?:month|year)|/\s*(?:mo|month|yr|year))\b", re.I)
_ONE = re.compile(r"\b(?:checkout|buy|purchase|order|pay\s+for|fee|one[-\s]?time|deposit|donat\w+|ticket)\b", re.I)
_GATE_APP = re.compile(r"\b(?:must|need(?:s)?\s+to|have\s+to|only)\b[^.]*\bsubscri\w*|\bmembers?\s+only\b|\bpaywall\b", re.I)
_OPEN_APP = re.compile(r"\b(?:free\s+to\s+use|stays?\s+open|optional)\b", re.I)
#: Words that ADD money to the app: beside a "don't"/"remove", the request is
#: still about taking payments ("don't forget to add a Pro plan with payments",
#: "remove the old billing page and charge through Razorpay").
_ADDS = re.compile(r"\b(?:add|create|set\s*up|connect|through|via|razorpay|stripe|paypal|plans?|prices?|priced|tiers?)\b", re.I)


def _says(name: str, text: str) -> bool:
    """`name` said as a word of its own: a gateway called "Main" is not in "maintain"."""
    return bool(name) and re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", text) is not None
def _org_gateways(output_dir: str) -> list[Any]:
    """The organisation's gateways, read through the same bridge the secret lookups use."""
    from services.figma.integrations import _org_for_output_dir, _run, _session_on_this_loop

    async def rows(org_id: Any) -> list[Any]:
        from services.payments.gateways import listing
        async with _session_on_this_loop() as db:
            return await listing(db, org_id)

    org_id = _run(_org_for_output_dir(output_dir))
    return _run(rows(org_id)) if org_id is not None else []


def run(output_dir: str, *, change: str = "", reasoning: Any = None) -> dict[str, Any]:
    from services.blueprint.service import BlueprintService
    from services.llm_client import tell
    from services.payments import app_payments as AP
    from services.payments import need as need_mod
    text = (change or "").strip()
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet.", "options": []}
    doc = svc.doc
    current = AP.section(doc)
    try:
        if _OFF.search(text) and not _ADDS.search(text) and not need_mod.plans_in_words(text, "USD"):
            AP.choose(svc, gateways=[], needed=False, by="smith", output_dir=str(output_dir))
            tell(reasoning, "Payments turned off.", "step")
            return {"applied": True, "edited_paths": ["src/lib/payments-config.ts"], "reason": "", "options": [],
                    "diff_summary": "The app takes no payments now. Its plans and checkouts are switched off; turn them on again any time."}
        rows = [r for r in _org_gateways(str(output_dir)) if r.deleted_at is None]
    except AP.ChoiceError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc), "options": [AP.PAYMENT_CHIP]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] payments setup failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "options": []}
    currency = need_mod.app_currency(doc)
    # WHICH GATEWAYS: the ones named; else the ones the app already has; else,
    # with exactly one connected, that one. Otherwise the person chooses.
    low = text.lower()
    from services.payments.gateways import status_of
    # A GATEWAY WHOSE KEYS WERE REFUSED IS NOT CHOSEN, named or not: it would
    # ship keys its gateway refuses, and every checkout would fail.
    usable = [r for r in rows if status_of(r) != "attention"]
    said = [r for r in rows if _says(r.provider, low) or _says(r.label or "", low)]
    refused = [r for r in said if status_of(r) == "attention"]
    named = [r for r in said if status_of(r) != "attention"]
    if refused and not named:
        names = ", ".join(r.label for r in refused)
        return {"applied": False, "edited_paths": [], "options": [AP.PAYMENT_CHIP],
                "reason": f"{names}'s keys were refused by the gateway, so it cannot take payments yet. An admin fixes them in "
                          "Settings → Integrations → Payments; then ask me again, or choose another gateway."}
    chosen = named or [r for r in usable if str(r.id) in {str(g.get("gateway")) for g in current.get("gateways") or []}]
    if not chosen and len(usable) == 1:
        chosen = usable
    models = list(current.get("models") or []) if current.get("needed") else []
    if _SUB.search(text) and "subscription" not in models:
        models.append("subscription")
    if _ONE.search(text) and "one_time" not in models:
        models.append("one_time")
    if not models:
        models = ["one_time"]
    plans = list(current.get("plans") or [])
    asked_plans = need_mod.plans_in_words(text, currency)
    if asked_plans:
        by_name = {p["name"].lower(): p for p in plans}
        for p in asked_plans:
            if p["name"].lower() in by_name:
                by_name[p["name"].lower()]["prices"].update(p["prices"])
                by_name[p["name"].lower()]["interval"] = p["interval"]
            else:
                plans.append(p)
    access = "app" if _GATE_APP.search(text) else "none" if _OPEN_APP.search(text) else current.get("access") or "none"
    if not rows:
        return {"applied": False, "edited_paths": [], "options": [AP.PAYMENT_CHIP],
                "reason": ("Your organisation has no payment gateway connected yet. An admin connects Razorpay, Stripe or PayPal "
                           "once in Settings → Integrations → Payments; then I build it in. Until then the app can take test payments that "
                           "charge nobody.")}
    if not chosen:
        names = ", ".join(r.label for r in rows)
        return {"applied": False, "edited_paths": [], "options": [AP.PAYMENT_CHIP],
                "reason": f"Which of your gateways should it use — {names}? Choose them (more than one is fine: payers are "
                          "sent to the right one by their currency)."}
    if "subscription" in models and not plans:
        plans = need_mod.clean_plans([{"name": "Monthly", "interval": "month", "price": need_mod._default_price(currency),
                                       "features": []}], currency)
    try:
        AP.choose(svc, gateways=chosen, needed=True, models=models, plans=plans, access=access, by="smith",
                  output_dir=str(output_dir))
    except AP.ChoiceError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc), "options": [AP.PAYMENT_CHIP]}
    tell(reasoning, AP.summarise(AP.section(svc.doc)), "step")
    said = AP.summarise(AP.section(svc.doc))
    if "subscription" in models:
        said += (" Its plans: " + "; ".join(f"{p['name']} " + ", ".join(f"{v:g} {c}" for c, v in p["prices"].items()) + f"/{p['interval']}"
                                            for p in AP.section(svc.doc).get("plans") or [])
                 + ". People choose and manage them at /billing in the app"
                 + (", and need an active plan to use it." if AP.section(svc.doc).get("access") == "app" else "."))
    if "one_time" in models:
        said += " Where a process should take a payment, tell me which (\"the order's checkout\") and I will add it."
    return {"applied": True, "edited_paths": ["src/lib/payments-config.ts", "src/middleware.ts"], "reason": "", "options": [],
            "diff_summary": said}


__all__ = ["VERB", "run"]

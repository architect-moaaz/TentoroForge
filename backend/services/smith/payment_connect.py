"""Connect the application's payments to a provider.

"Connect Stripe": one integration row `serves: take_payment` with the
provider's key NAMES and its `inbound` (the provider signs its own calls),
projected into the app; the reply says the webhook address to register
at the provider and the names still unset. A second provider is one entry
in `SERVICES` here and one file in the runtime's registry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SERVES = "take_payment"
LIVE_KEY: dict[str, str] = {"stripe": "STRIPE_SECRET_KEY"}
FROM_KEY = ""
EVENTS = ["payment.succeeded", "payment.failed", "refund.succeeded", "account.updated"]


@dataclass(frozen=True)
class PaymentService:
    name: str
    provider: str
    words: tuple[str, ...]
    keys: tuple[str, ...]
    webhook_secret: str
    caveat: str = ""


SERVICES: tuple[PaymentService, ...] = (
    PaymentService("Stripe", "stripe", ("stripe",), ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLISHABLE_KEY"),
                   "STRIPE_WEBHOOK_SECRET", "Hosted checkout; Connect Express for split payouts."),
)
CHOICES: tuple[str, ...] = tuple(s.name for s in SERVICES)


class NoPaymentAdapter(LookupError):
    """The service named is not one the runtime can take payments through."""


def keys_for(provider: str) -> list[str]:
    svc = next((s for s in SERVICES if s.provider == provider), None)
    return list(svc.keys) if svc else []


def service_for(said: str) -> PaymentService | None:
    text = (said or "").lower()
    best: PaymentService | None = None
    best_len = 0
    for svc in SERVICES:
        for word in svc.words:
            if word in text and len(word) > best_len:
                best, best_len = svc, len(word)
    return best


def declared(doc: dict) -> dict | None:
    for row in doc.get("integrations") or []:
        if isinstance(row, dict) and str(row.get("serves") or "") == SERVES \
                and str(row.get("status") or "").upper() not in ("DEPRECATED", "REMOVED"):
            return row
    return None


def connect(svc: Any, *, service: str, output_dir: str | None = None, reasoning: Any = None) -> dict[str, Any]:
    from services.blueprint.ids import integration_key
    from services.llm_client import tell
    from services.smith.section_change import record_requirement
    chosen = service_for(service)
    if chosen is None:
        raise NoPaymentAdapter(service)
    req = record_requirement(svc, f"Take payments through {chosen.name}.", owner="integrations")
    for row in svc.doc.get("integrations") or []:
        if isinstance(row, dict) and str(row.get("serves") or "") == SERVES and str(row.get("name") or "") != chosen.name:
            row["status"] = "DEPRECATED"
    before = svc.snapshot()
    row = svc.upsert("integrations", {
        "name": chosen.name, "kind": "payment", "provider": chosen.provider, "secretRefs": list(chosen.keys),
        "serves": SERVES, "status": "APPROVED",
        "inbound": {"events": list(EVENTS), "verify": "provider", "signingSecretRef": chosen.webhook_secret},
        "requirements": [str(req.get("id"))] if req.get("id") else [],
    }, natural_key=integration_key(chosen.name))
    svc.commit(user_request=f"connect payments to {service}".strip(),
               smith_interpretation=f"take payments through {chosen.name}; live once {LIVE_KEY[chosen.provider]} is set",
               before=before, affected=[str(row.get("id") or "")])
    tell(reasoning, f"Recorded {chosen.name} as the service that takes this application's payments.", "step")
    files: list[str] = []
    set_keys: set[str] = set()
    if output_dir:
        from pathlib import Path

        from services.blueprint.projection import project_integrations
        app_root = Path(output_dir) / "app"
        if app_root.is_dir():
            files = list(project_integrations(svc.doc, app_root).get("files") or [])
        try:
            from services.platform_secrets import keys_set_for
            set_keys = set(keys_set_for(output_dir, list(chosen.keys)))
        except Exception:  # noqa: BLE001 — no store reachable: nothing is set
            set_keys = set()
    return {"applied": True, "integration": str(row.get("id") or ""), "name": chosen.name, "provider": chosen.provider,
            "secrets": list(chosen.keys), "set": sorted(set_keys), "missing": [k for k in chosen.keys if k not in set_keys],
            "connected": LIVE_KEY[chosen.provider] in set_keys, "edited_paths": files}


def summarise(out: dict[str, Any]) -> str:
    from services.blueprint.projection import integration_slug
    slug = integration_slug({"name": out.get("name")})
    missing = ", ".join(out.get("missing") or [])
    return (f"Payments now go through {out.get('name')}. "
            + ("It is live. " if out.get("connected") else f"Set {missing} under Settings → Integrations to make it live; until then a stand-in takes payments and says so. ")
            + f"Register this address at {out.get('name')} for its events: `/api/webhooks/{slug}` (its signed calls settle the ledger).")


def refusal(said: str, doc: dict) -> tuple[str, list[str]]:
    return (f"I cannot take payments through {said!r}: the only payment service this application can talk to is "
            f"{', '.join(CHOICES)}. Name it, or say what the other one should do and I will declare it.",
            [f"Connect {c}" for c in CHOICES])


def run(output_dir: str, *, service: str, reasoning: Any = None) -> dict[str, Any]:
    from services.blueprint.service import BlueprintService
    from services.smith.secrets_scrub import scrub
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet.", "options": []}
    try:
        out = connect(svc, service=service, output_dir=str(output_dir), reasoning=reasoning)
    except NoPaymentAdapter:
        why, options = refusal(scrub(service), svc.doc)
        return {"applied": False, "edited_paths": [], "reason": why, "options": options}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] connect payments failed for %r", service)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}", "options": []}
    return {"applied": True, "edited_paths": list(out.get("edited_paths") or []), "diff_summary": summarise(out),
            "reason": "", "options": [], **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["CHOICES", "EVENTS", "LIVE_KEY", "SERVES", "SERVICES", "connect", "declared", "keys_for", "refusal",
           "run", "service_for", "summarise"]

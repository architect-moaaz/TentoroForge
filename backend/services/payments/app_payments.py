"""An application's payments: what the Blueprint records, what each build
agent is told, what the app is given, and which keys reach it where.

The organisation's gateways are its own (`services.payments.gateways`); an
application RECORDS which of them it uses (`payments.gateways`, by id), what it
sells (`models`, `plans`) and whether a subscription opens it (`access`). From
that record, and nothing else:

* every build agent whose work it shapes is told (`agent_note`),
* one integration row per chosen gateway serves `take_payment`, so the
  checks and processes written before gateways were chosen keep working,
* the app gets `src/lib/payments-config.ts` (`project_config`) and the
  platform's payment files (`install_runtime`),
* its middleware locks the app to subscribers when `access` says so
  (`middleware_gate`),
* and its environment gets each chosen gateway's keys by NAME
  (`env_for_side`): test keys for a preview and the test version, live keys
  only in production. A gateway with no keys for a side is left out of it,
  and the app's stand-in says so.

Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Iterable

from services.payments import need as need_mod
from services.payments import providers as P

logger = logging.getLogger(__name__)

SERVES = "take_payment"

#: The environment variable each stored key goes into, per gateway.
FIELD_ENV: dict[str, dict[str, str]] = {
    "stripe": {"secret_key": "STRIPE_SECRET_KEY", "publishable_key": "STRIPE_PUBLISHABLE_KEY"},
    "razorpay": {"key_id": "RAZORPAY_KEY_ID", "key_secret": "RAZORPAY_KEY_SECRET"},
    "paypal": {"client_id": "PAYPAL_CLIENT_ID", "client_secret": "PAYPAL_CLIENT_SECRET"},
}
#: The variable the webhook's signing secret (PayPal: its webhook id) goes into.
WEBHOOK_ENV = {"stripe": "STRIPE_WEBHOOK_SECRET", "razorpay": "RAZORPAY_WEBHOOK_SECRET", "paypal": "PAYPAL_WEBHOOK_ID"}
#: Every name any gateway reads — what a side WITHOUT that gateway must not carry.
ALL_ENV = sorted({n for m in FIELD_ENV.values() for n in m.values()} | set(WEBHOOK_ENV.values()) | {"PAYPAL_ENV"})

#: The events each gateway's webhook is registered for.
WEBHOOK_EVENTS: dict[str, list[str]] = {
    "stripe": ["checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed",
               "checkout.session.expired", "charge.refunded", "customer.subscription.created", "customer.subscription.updated",
               "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"],
    "razorpay": ["payment.captured", "payment.failed", "order.paid", "refund.processed", "subscription.authenticated",
                 "subscription.activated", "subscription.charged", "subscription.pending", "subscription.halted",
                 "subscription.cancelled", "subscription.completed", "subscription.paused", "subscription.resumed"],
    "paypal": ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.SALE.COMPLETED",
               "BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.UPDATED", "BILLING.SUBSCRIPTION.SUSPENDED",
               "BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED", "BILLING.SUBSCRIPTION.PAYMENT.FAILED"],
}

_RETIRED = ("DEPRECATED", "REMOVED", "SUPERSEDED", "REJECTED")


def section(doc: dict) -> dict:
    p = doc.get("payments")
    return p if isinstance(p, dict) else {}


def takes_money(doc: dict) -> bool:
    return bool(section(doc).get("needed"))


def sells_plans(doc: dict) -> bool:
    p = section(doc)
    return bool(p.get("needed")) and "subscription" in (p.get("models") or []) and bool(p.get("plans"))


def integration_slug(provider: str) -> str:
    return provider.lower()


# --------------------------------------------------------------------------- #
# What each build agent is told
# --------------------------------------------------------------------------- #

def agent_note(doc: dict, node: str) -> str:
    """One paragraph for the agents whose work the payment decision shapes;
    "" for the rest, or when nothing has been decided."""
    p = section(doc)
    if p.get("needed") is None:
        return ""
    needed = bool(p.get("needed"))
    models = list(p.get("models") or [])
    chosen = [g for g in p.get("gateways") or [] if isinstance(g, dict)]
    names = ", ".join(f"{g.get('label') or g.get('provider')} (provider `{g.get('provider')}`)" for g in chosen)
    if node == "integrations":
        if not needed:
            return ("PAYMENTS: the owner decided this application takes NO payments. Declare no payment service "
                    "(nothing that serves `take_payment`).")
        if chosen:
            return ("PAYMENTS ARE ALREADY DECIDED BY THE OWNER: the application takes money through " + names + ". "
                    "Their integrations are declared (one per gateway, `serves: take_payment`); do not declare any other "
                    "payment service and do not change, rename or remove these.")
        return ("PAYMENTS: the application takes money, but the owner has not connected a gateway yet. Declare no payment "
                "integration yourself; the platform adds the gateways the owner chooses, and a stand-in takes payments until then.")
    if node in ("workflows", "workflow_steps"):
        if not needed:
            return ("PAYMENTS: this application takes no money. Write no `create_checkout`, `refund_payment` or "
                    "`connect_account` step.")
        parts = []
        if "one_time" in models:
            parts.append("ONE-TIME PAYMENTS: where a person pays for something (an order, a booking, a fee), the process "
                         "ends with `create_checkout` and a second process, triggered by `webhook` on the payment "
                         "integration's `payment.succeeded`, records the outcome on the record it was for. The app routes "
                         "each payer to the right gateway by itself.")
        else:
            parts.append("Write no `create_checkout` step: nothing here is a one-time purchase.")
        if "subscription" in models:
            parts.append("SUBSCRIPTIONS ARE BUILT IN: the application ships its own plans, checkout, billing page "
                         "(`/billing`) and access check. Do not write processes that charge for a plan, renew one or "
                         "cancel one, and do not model plans or subscriptions as records. Where a step must know "
                         "whether the acting person holds a plan, it reads `$user.subscribed` (true or false) and "
                         "`$user.plan` (the plan's id: " + ", ".join(f"`{pl.get('id')}`" for pl in p.get("plans") or []) + ").")
        return "PAYMENTS: " + " ".join(parts)
    if node == "business_rules" and needed and "subscription" in models:
        return ("PAYMENTS: who holds a plan is the application's own (built-in subscriptions). A rule that depends on "
                "it reads `user.subscribed` (true or false) or `user.plan` (the plan's id: "
                + ", ".join(f"`{pl.get('id')}`" for pl in p.get("plans") or []) + "); never a Membership or "
                "Subscription record.")
    if node in ("data_model", "entity_fields") and "subscription" in models and needed:
        return ("PAYMENTS: subscriptions are built into the application (its own tables hold who subscribed to which plan). "
                "Do not declare Plan, Subscription, Membership or Billing records for them.")
    if node in ("ux_architecture", "page_contracts", "page_details") and needed:
        if "subscription" in models:
            return ("PAYMENTS: the application ships its own plan & billing page at `/billing` (plans, checkout, the "
                    "subscriber's plan, cancel). Do not declare a pricing, plans, subscription or billing page; link to "
                    "`/billing` where a page should send people to choose a plan.")
        return ""
    return ""


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #

def state(doc: dict) -> dict[str, Any]:
    """What the build dialog and the Payments panel draw."""
    p = section(doc)
    return {
        "needed": p.get("needed"), "models": list(p.get("models") or []), "reason": str(p.get("reason") or ""),
        "decidedBy": p.get("decidedBy"), "gateways": list(p.get("gateways") or []), "plans": list(p.get("plans") or []),
        "access": p.get("access") or "none", "currency": need_mod.app_currency(doc),
        "decided": p.get("decidedBy") in ("person", "smith"),
    }


def decide_and_record(svc: Any, *, provider: Any = None, force: bool = False) -> dict[str, Any]:
    """Decide whether the app takes money when nobody has, or the definition
    changed since Forge last did. A person's (or Smith's) decision is kept.
    Writes through `svc.commit` only when something changed."""
    doc = svc.doc
    p = section(doc)
    basis = need_mod.basis(doc)
    if p.get("decidedBy") in ("person", "smith") and not force:
        return state(doc)
    if p.get("decidedBy") == "forge" and p.get("basis") == basis and not force:
        return state(doc)
    found = need_mod.decide(doc, provider=provider)
    before = svc.snapshot()
    new = {**p, "needed": bool(found["needed"]), "models": list(found["models"]), "reason": found["reason"],
           "access": found.get("access") or "none", "decidedBy": "forge", "basis": basis,
           # Forge's own earlier plans are its guess too (a person's choice never
           # reaches here): a new decision brings its own, or keeps the last.
           "plans": list(found.get("plans") or []) or list(p.get("plans") or [])}
    new.setdefault("gateways", [])
    if new == p:
        return state(doc)
    doc["payments"] = new
    try:
        svc.validate()
    except Exception:  # noqa: BLE001 — a decision that does not fit the contract is not written
        logger.exception("[payments] the decision did not validate; not recorded")
        doc["payments"] = p
        return state(doc)
    svc.commit(user_request="Decide whether the application takes payments",
               smith_interpretation=f"payments: {'yes — ' + ', '.join(new['models']) if new['needed'] else 'no'} ({found.get('by')})",
               before=before, affected=[])
    return state(svc.doc)


class ChoiceError(ValueError):
    pass


def _clean_choice_plans(plans: Any, currencies: set[str], app_currency: str) -> list[dict]:
    cleaned = need_mod.clean_plans(plans, app_currency, limit=8) if isinstance(plans, list) else []
    for p in cleaned:
        bad = [c for c in p["prices"] if currencies and c not in currencies]
        if bad:
            raise ChoiceError(f"{p['name']} is priced in {', '.join(bad)}, which none of the chosen gateways takes. "
                              f"They take {', '.join(sorted(currencies))}.")
    return cleaned


def choose(svc: Any, *, gateways: list[Any], needed: bool, models: list[str] | None = None, plans: list[dict] | None = None,
           access: str | None = None, by: str = "person", output_dir: str | None = None) -> dict[str, Any]:
    """Record the owner's choice: which of the organisation's gateways the app
    takes money through (rows from `services.payments.gateways`), what it sells
    and whether a subscription opens it. Raises ChoiceError with the sentence
    to show. Projects the result into the app when it exists."""
    doc = svc.doc
    p = dict(section(doc))
    before = svc.snapshot()
    if not needed:
        p.update(needed=False, models=[], decidedBy=by, gateways=[], access="none")
        p.setdefault("reason", "")
        p["reason"] = "You chose to build it without payments." if by == "person" else (p.get("reason") or "")
    else:
        models = [m for m in (models or p.get("models") or []) if m in ("one_time", "subscription")] or ["one_time"]
        chosen: list[dict] = []
        providers_seen: set[str] = set()
        for row in gateways:
            prov = str(getattr(row, "provider", "") or "")
            if prov in providers_seen:
                raise ChoiceError(f"Choose one {P.PROVIDERS[prov].name} account for an app, not two.")
            providers_seen.add(prov)
            chosen.append({"gateway": str(row.id), "provider": prov, "label": str(row.label),
                           "coverage": str(row.coverage), "homeCountry": row.home_country,
                           "currencies": [str(c) for c in (row.currencies or [])]})
        currencies = {c for g in chosen for c in g["currencies"]}
        app_currency = need_mod.app_currency(doc)
        clean = _clean_choice_plans(plans if plans is not None else p.get("plans") or [], currencies, app_currency) \
            if "subscription" in models else []
        if "subscription" in models and not clean:
            raise ChoiceError("A subscription needs at least one plan with a price.")
        if chosen and app_currency not in currencies and "one_time" in models:
            raise ChoiceError(f"The app's prices are in {app_currency}, and none of the chosen gateways takes {app_currency}. "
                              f"Add a gateway that does, or change the app's currency.")
        p.update(needed=True, models=models, plans=clean, gateways=chosen, decidedBy=by,
                 access=(access if access in ("app", "none") else p.get("access") or "none") if "subscription" in models else "none")
        if not p.get("reason"):
            p["reason"] = "You chose to take payments."
    doc["payments"] = p
    _sync_integrations(svc)
    try:
        svc.validate()
    except Exception as exc:  # noqa: BLE001
        raise ChoiceError(f"The choice does not fit the app's definition: {str(exc)[:300]}") from exc
    record = svc.commit(user_request="Choose how the application takes payments",
                        smith_interpretation=summarise(p), before=before,
                        affected=[str(r.get("id")) for r in doc.get("integrations") or [] if isinstance(r, dict)
                                  and r.get("serves") == SERVES and r.get("id")])
    if output_dir:
        app = Path(output_dir) / "app"
        if app.is_dir():
            try:
                project_into(svc.doc, app)
            except Exception:  # noqa: BLE001 — the choice stands; the next sync writes it
                logger.exception("[payments] projecting the choice failed")
    return {**state(svc.doc), "version": int(record.get("version") or 0) if isinstance(record, dict) else 0}


def summarise(p: dict) -> str:
    if not p.get("needed"):
        return "No payments."
    what = " and ".join({"one_time": "one-time payments", "subscription": "subscriptions"}[m] for m in p.get("models") or [])
    through = ", ".join(g.get("label") or g.get("provider") for g in p.get("gateways") or []) or "the stand-in until a gateway is chosen"
    return f"Takes {what} through {through}."


def _sync_integrations(svc: Any) -> None:
    """One integration row per chosen gateway (`serves: take_payment`); a
    payment row of a gateway no longer chosen is retired. Rows of the same
    provider are updated in place, so their ids — and the processes whose
    webhook trigger names them — stay."""
    from services.blueprint.ids import integration_key
    from services.smith.payment_connect import EVENTS, SERVICES
    doc = svc.doc
    chosen = {g["provider"] for g in section(doc).get("gateways") or []}
    for row in doc.get("integrations") or []:
        if isinstance(row, dict) and row.get("serves") == SERVES and str(row.get("status") or "") not in _RETIRED \
                and str(row.get("provider") or "") not in chosen and chosen:
            row["status"] = "DEPRECATED"
    for g in section(doc).get("gateways") or []:
        svc_info = next((s for s in SERVICES if s.provider == g["provider"]), None)
        if svc_info is None:
            continue
        existing = next((r for r in doc.get("integrations") or [] if isinstance(r, dict) and r.get("serves") == SERVES
                         and r.get("provider") == g["provider"] and str(r.get("status") or "") not in _RETIRED), None)
        body = {"name": svc_info.name, "kind": "payment", "provider": svc_info.provider, "secretRefs": list(svc_info.keys),
                "serves": SERVES, "status": "APPROVED",
                "inbound": {"events": list(EVENTS) + ["subscription.updated"], "verify": "provider",
                            "signingSecretRef": svc_info.webhook_secret}}
        if existing is not None:
            existing.update({k: v for k, v in body.items() if k != "name"})
            continue
        svc.upsert("integrations", body, natural_key=integration_key(svc_info.name))


# --------------------------------------------------------------------------- #
# Into the application
# --------------------------------------------------------------------------- #

def config_text(doc: dict) -> str:
    p = section(doc)
    cfg = {
        "needed": bool(p.get("needed")),
        "currency": need_mod.app_currency(doc),
        "models": list(p.get("models") or []) if p.get("needed") else [],
        "access": p.get("access") or "none",
        "gateways": [{"id": g.get("gateway"), "provider": g.get("provider"), "label": g.get("label") or g.get("provider"),
                      "coverage": g.get("coverage") or "both", "homeCountry": g.get("homeCountry"),
                      "currencies": list(g.get("currencies") or []), "integration": integration_slug(str(g.get("provider") or "")),
                      "isDefault": i == 0}
                     for i, g in enumerate(p.get("gateways") or []) if isinstance(g, dict)] if p.get("needed") else [],
        "plans": list(p.get("plans") or []) if p.get("needed") else [],
    }
    return ("// Generated from the Living Blueprint (`payments`). Edit the Blueprint, not this file.\n"
            "//\n"
            "// Whether the application takes money, through which of its owner's gateways\n"
            "// (never a key: those arrive in the environment by name), the plans it sells\n"
            "// and whether a subscription opens it. Read by `src/lib/payments`.\n\n"
            "export interface PaymentsConfig {\n"
            "  needed: boolean; currency: string; models: string[]; access: \"app\" | \"none\";\n"
            "  gateways: Array<{ id: string; provider: string; label: string; coverage: \"domestic\" | \"international\" | \"both\";\n"
            "    homeCountry?: string | null; currencies: string[]; integration: string; isDefault?: boolean }>;\n"
            "  plans: Array<{ id: string; name: string; description?: string; interval: \"day\" | \"week\" | \"month\" | \"year\";\n"
            "    intervalCount: number; prices: Record<string, number>; trialDays: number; features: string[]; highlighted?: boolean }>;\n"
            "}\n\n"
            f"export const PAYMENTS: PaymentsConfig = {json.dumps(cfg, indent=2, ensure_ascii=False, sort_keys=True)};\n")


def project_config(doc: dict, app_root: str | Path) -> dict[str, Any]:
    path = Path(app_root) / "src" / "lib" / "payments-config.ts"
    text = config_text(doc)
    try:
        if path.read_text("utf-8") == text:
            return {"files": []}
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return {"files": ["src/lib/payments-config.ts"]}


#: The platform's payment files: template (under templates/runtime) -> where the app keeps it.
RUNTIME_FILES: tuple[tuple[str, str], ...] = (
    ("api-billing/_session.ts", "src/app/api/billing/_session.ts"),
    ("api-billing/subscribe/route.ts", "src/app/api/billing/subscribe/route.ts"),
    ("api-billing/return/route.ts", "src/app/api/billing/return/route.ts"),
    ("api-billing/cancel/route.ts", "src/app/api/billing/cancel/route.ts"),
    ("api-billing/status/route.ts", "src/app/api/billing/status/route.ts"),
    ("api-billing/access/route.ts", "src/app/api/billing/access/route.ts"),
    ("api-billing/manage/route.ts", "src/app/api/billing/manage/route.ts"),
    ("api-pay/stand-in/route.ts", "src/app/api/pay/stand-in/route.ts"),
    ("api-pay/return/route.ts", "src/app/api/pay/return/route.ts"),
    ("api-pay/confirm/route.ts", "src/app/api/pay/confirm/route.ts"),
    ("pages/pay/stand-in/page.tsx", "src/app/pay/stand-in/page.tsx"),
    ("pages/pay/razorpay/page.tsx", "src/app/pay/razorpay/page.tsx"),
    ("pages/pay/razorpay/RazorpayCheckout.tsx", "src/app/pay/razorpay/RazorpayCheckout.tsx"),
    ("pages/billing/page.tsx", "src/app/(dashboard)/billing/page.tsx"),
    ("pages/billing/BillingClient.tsx", "src/app/(dashboard)/billing/BillingClient.tsx"),
    ("db/forge-payments.schema.ts", "src/db/schema/_forge_payments.ts"),
    ("db/forge-billing.schema.ts", "src/db/schema/_forge_billing.ts"),
    # Where the gateways' signed events land, and how each is verified. A build
    # writes both; an app from before them would answer the webhook publish
    # registers with a 404 until the gateway gave up on it.
    ("integrations/providers.ts", "src/lib/integrations/providers.ts"),
    ("api-webhooks/route.ts", "src/app/api/webhooks/[integration]/route.ts"),
)
_BARREL = {"_forge_payments": "export { forgePayments } from \"./_forge_payments\";",
           "_forge_billing": "export { forgeSubscriptions, forgePlanRefs } from \"./_forge_billing\";"}


def install_runtime(app_root: str | Path, doc: dict | None = None) -> list[str]:
    """Write the platform's payment files into an application, where they
    differ; export its tables from the schema barrel; project its config.
    Never deletes. Returns what changed, relative to the app."""
    from services.runtime_injector import _TEMPLATE_DIR
    root = Path(app_root)
    if not (root / "package.json").is_file() and not (root / "src").is_dir():
        return []
    changed: list[str] = []
    # THE LIBRARY THE ROUTES IMPORT (`@/lib/payments/*`). A build copies it
    # with the other engine directories and a Smith sync refreshes it, but an
    # app built before it existed that is given payments from its Payments tab
    # gets only what this function writes: its billing routes would import a
    # module that is not there, and the app would not compile.
    lib = _TEMPLATE_DIR / "payments"
    files = sorted(f for f in lib.rglob("*") if f.is_file()) if lib.is_dir() else []
    for f in files:
        if "__tests__" in f.parts or f.name.endswith((".test.ts", ".spec.ts")):
            continue
        rel = f"src/lib/payments/{f.relative_to(lib).as_posix()}"
        dst = root / rel
        try:
            if dst.is_file() and dst.read_bytes() == f.read_bytes():
                continue
        except OSError:
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst)
        changed.append(rel)
    for tmpl, rel in RUNTIME_FILES:
        src, dst = _TEMPLATE_DIR / tmpl, root / rel
        if not src.is_file():
            continue
        # THE TABLES BEFORE THE BARREL. Given the definition (a sync, a
        # publish, a choice), the data layer is written from it next, and its
        # barrel exports the `_forge_*` tables it finds: waiting for the folder
        # it makes put these a sync behind, so a second sync was never
        # "already matches". Without it, an app with no schema folder has no
        # database for them.
        if rel.startswith("src/db/") and doc is None and not (root / "src" / "db" / "schema").is_dir():
            continue
        try:
            if dst.is_file() and dst.read_bytes() == src.read_bytes():
                continue
        except OSError:
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        changed.append(rel)
    # THE APP'S CURRENCY, which the library falls back to (`@/lib/money`). A
    # build writes it; an app from before that has none, and a bundler refuses
    # an import it cannot resolve, inside a try or not.
    if not (root / "src" / "lib" / "money.ts").is_file():
        from services.blueprint.projection import project_money
        changed += project_money(doc or {}, root).get("files") or []
    barrel = root / "src" / "db" / "schema" / "index.ts"
    if barrel.is_file():
        text = barrel.read_text("utf-8")
        add = [line for name, line in _BARREL.items() if f"./{name}\"" not in text]
        if add:
            barrel.write_text(text.rstrip() + "\n" + "\n".join(add) + "\n", "utf-8")
            changed.append("src/db/schema/index.ts")
    if doc is not None or not (root / "src" / "lib" / "payments-config.ts").is_file():
        changed += project_config(doc or {}, root).get("files") or []
    return changed


def project_into(doc: dict, app_root: str | Path) -> list[str]:
    """After a choice: the config, the integrations' bindings and the middleware's gate."""
    from services.blueprint.projection import project_integrations, project_middleware
    # THE CURRENT ENGINE, as a Smith turn and a publish bring it (which runs
    # `install_runtime` too). An app built before the payment routes carries a
    # workflow engine that sends a payer straight back to its page, past
    # `/api/pay/return` — which asks the gateway, and is where PayPal's order is
    # captured: without it, nothing would ever be charged.
    try:
        from services.smith.sync_app import refresh_engine
        files = refresh_engine(app_root, doc)
    except Exception:  # noqa: BLE001 — the payment files alone are still better than none
        logger.exception("[payments] the engine could not be refreshed")
        files = install_runtime(app_root, doc)
    files += list(project_integrations(doc, app_root).get("files") or [])
    try:
        files += list(project_middleware(doc, app_root).get("files") or [])
    except Exception:  # noqa: BLE001 — a middleware that cannot be written keeps its last version
        logger.exception("[payments] the middleware could not be written")
    return files


# --------------------------------------------------------------------------- #
# The middleware's gate: a subscription opens the application
# --------------------------------------------------------------------------- #

#: What a person without a subscription still reaches: signing in, choosing a
#: plan and paying for it, and what calls the app from outside.
GATE_FREE = (r"^/billing(?:/.*)?$", r"^/api/billing(?:/.*)?$", r"^/pay(?:/.*)?$", r"^/api/pay(?:/.*)?$",
             r"^/api/auth(?:/.*)?$", r"^/login$", r"^/signup$", r"^/set-password$", r"^/403$", r"^/offline$",
             r"^/api/webhooks(?:/.*)?$", r"^/api/cron(?:/.*)?$", r"^/api/notifications(?:/.*)?$")
#: The app's own operators use it without subscribing.
OPERATOR_ROLES = ("admin", "administrator", "owner", "superadmin", "super_admin")


def middleware_gate(doc: dict) -> tuple[list[str], list[str]]:
    """(lines before `export default`, lines inside the middleware after the
    role checks) — empty when no subscription opens the app."""
    p = section(doc)
    if not (sells_plans(doc) and p.get("access") == "app"):
        return [], []
    head = [
        "// A SUBSCRIPTION OPENS THIS APPLICATION (`payments.access: \"app\"`). A signed-in",
        "// person without one reaches only signing in, the plans and paying for one; the",
        "// app's operators are not asked. The access token is short-lived and signed",
        "// with the app's own secret (`src/lib/payments/billing.ts`); a missing or",
        "// expired one is checked against the subscription itself (`/api/billing/access`).",
        "const GATE_FREE: RegExp[] = [" + ", ".join(f"new RegExp({json.dumps(r)})" for r in GATE_FREE) + "];",
        f"const OPERATORS = new Set({json.dumps(list(OPERATOR_ROLES))});",
        "async function holdsAccess(req: any, uid: string): Promise<boolean> {",
        "  const raw = req.cookies?.get?.(\"forge_access\")?.value ?? \"\";",
        "  const secret = process.env.NEXTAUTH_SECRET ?? process.env.AUTH_SECRET ?? \"\";",
        "  const [body, sig] = raw.split(\".\");",
        "  if (!body || !sig || !secret) return false;",
        "  try {",
        "    const text = atob(body.replace(/-/g, \"+\").replace(/_/g, \"/\"));",
        "    const [who, until] = text.split(\".\");",
        "    if (who !== uid || !(Number(until) * 1000 > Date.now())) return false;",
        "    const key = await crypto.subtle.importKey(\"raw\", new TextEncoder().encode(secret), { name: \"HMAC\", hash: \"SHA-256\" }, false, [\"sign\"]);",
        "    const mac = new Uint8Array(await crypto.subtle.sign(\"HMAC\", key, new TextEncoder().encode(text)));",
        "    let bin = \"\"; for (const b of mac) bin += String.fromCharCode(b);",
        "    const expected = btoa(bin).replace(/\\+/g, \"-\").replace(/\\//g, \"_\").replace(/=+$/, \"\");",
        "    return expected.length === sig.length && expected === sig;",
        "  } catch {",
        "    return false;",
        "  }",
        "}",
        "",
    ]
    body = [
        "    if (token && !GATE_FREE.some((r) => r.test(path)) && !OPERATORS.has(role.toLowerCase())) {",
        "      const uid = String((token as any).id ?? (token as any).sub ?? \"\");",
        "      if (!(await holdsAccess(req, uid))) {",
        "        if (isApi(path)) return NextResponse.json({ error: { code: \"SUBSCRIPTION_REQUIRED\", message: \"Choose a plan to use this.\" } }, { status: 402 });",
        "        const to = req.nextUrl.clone();",
        "        to.pathname = \"/api/billing/access\";",
        "        to.search = `?next=${encodeURIComponent(path + (req.nextUrl.search ?? \"\"))}`;",
        "        return NextResponse.redirect(to);",
        "      }",
        "    }",
    ]
    return head, body


# --------------------------------------------------------------------------- #
# Keys, by side
# --------------------------------------------------------------------------- #

def env_for_side(doc: dict, rows: Iterable[Any], side: str, *, webhooks: dict[str, str] | None = None) -> dict[str, str | None]:
    """The variables a side of this app gets for its chosen gateways.

    `side`: "local" (a preview on the platform) and "test" get each gateway's
    TEST keys; "production" its LIVE keys. A gateway without keys for the side
    gets nothing (and the app's stand-in says so). Every payment variable the
    side should NOT carry is returned as None, so a writer removes it — a live
    key never lingers in a preview. `webhooks`: provider -> signing secret (or
    PayPal webhook id) registered for this side."""
    from services.payments.gateways import keys_of
    mode = P.LIVE if side == "production" else P.TEST
    by_id = {str(r.id): r for r in rows}
    out: dict[str, str | None] = {name: None for name in ALL_ENV}
    if not takes_money(doc):
        return out
    for g in section(doc).get("gateways") or []:
        row = by_id.get(str(g.get("gateway")))
        if row is None or getattr(row, "deleted_at", None) is not None:
            continue
        keys = keys_of(row, mode)
        if not keys:
            continue
        for field, name in FIELD_ENV.get(row.provider, {}).items():
            if keys.get(field):
                out[name] = keys[field]
        if row.provider == "paypal":
            out["PAYPAL_ENV"] = "live" if mode == P.LIVE else "sandbox"
        hook = (webhooks or {}).get(row.provider)
        if hook:
            out[WEBHOOK_ENV[row.provider]] = hook
    return out


__all__ = ["ALL_ENV", "ChoiceError", "FIELD_ENV", "GATE_FREE", "RUNTIME_FILES", "SERVES", "WEBHOOK_ENV", "WEBHOOK_EVENTS",
           "agent_note", "choose", "config_text", "decide_and_record", "env_for_side", "install_runtime", "integration_slug",
           "middleware_gate", "project_config", "project_into", "section", "sells_plans", "state", "summarise", "takes_money"]


def build_question(svc: Any) -> dict[str, Any] | None:
    """Before a build a person approved: when the app takes money and nobody has
    chosen how, the message that opens the gateway dialog (and the build waits).
    Decides first when nothing was decided. None: build."""
    try:
        decided = decide_and_record(svc)
    except Exception:  # noqa: BLE001 — a decision that could not be made never blocks a build
        logger.exception("[payments] could not decide before the build")
        return None
    if not decided.get("needed") or decided.get("decided"):
        return None
    what = " and ".join({"one_time": "takes one-time payments", "subscription": "sells subscriptions"}[m]
                        for m in decided.get("models") or []) or "takes payments"
    return {"text": f"This app {what}: {decided.get('reason') or ''} Choose which of your payment gateways it uses — "
                    "or build it without payments for now — and the build starts.".replace(":  ", ": "),
            "status": "asked", "paymentChoice": True}


#: The chip that opens the gateway dialog in the panel (never sent as text).
PAYMENT_CHIP = "Choose payment gateways"


def sense_after_change(output_dir: str | Path, asked: str = "") -> dict[str, Any] | None:
    """After a Smith turn changed the app: did the change make it take money
    when nothing says how? (A checkout step appeared, a priced plan or
    subscription record, or the person asked for paid plans.) Then Forge
    decides — never over a person's choice — and the turn ends asking which
    gateways, with the chip that opens the dialog. None: nothing to ask."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except (FileNotFoundError, ValueError):
        return None
    doc = svc.doc
    p = section(doc)
    if p.get("needed") is True and p.get("gateways"):
        return None
    sig = need_mod.signals(doc)
    words = bool(need_mod._SUBSCRIPTION_WORDS.search(asked or "") or need_mod._ONE_TIME_WORDS.search(asked or ""))
    if not (sig["checkout"] or sig["sub_entities"] or words):
        return None
    if p.get("needed") is True and not p.get("gateways"):
        decided = state(doc)
    else:
        decided = decide_and_record(svc, force=p.get("decidedBy") == "forge")
    if not decided.get("needed"):
        return None
    what = " and ".join({"one_time": "takes payments", "subscription": "sells subscriptions"}[m]
                        for m in decided.get("models") or []) or "takes payments"
    return {"said": f"With this change the app {what}. Choose which of your payment gateways it uses — "
                    "Razorpay for India, Stripe or PayPal for everyone else — and I will build it in.",
            "options": [PAYMENT_CHIP]}

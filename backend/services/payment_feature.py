"""Payment-methods surface module.

Ensures every app that should have "Payment methods" gets a discoverable,
working screen (list + add-card form + nav entry). The DB table + CRUD
workflows for ``PaymentMethod`` are emitted by the rest of the pipeline —
this module just fills the visible gap.

Detection (Spec D W2 — planner-authored precedence only):
  1. Any entity carries ``needs_payment_methods: True`` — planner wins.
     Explicit ``False`` on every entity acts as an opt-out.
  2. A ``PaymentMethod``/``PaymentMethods`` entity exists (structural — the
     planner declared it directly).
  3. Any entity is flagged ``commerce: True`` (cart / commerce path).
Otherwise, no signal.

The regex-based transactional-amount fallback ("Booking has totalAmount so
it needs saved cards") was removed as part of Spec D W2 — the planner is
now the authority; over-eager keyword sweeps are gone.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── detection ──────────────────────────────────────────────────────────

# Structural names the planner uses for the saved-cards entity.
_PAYMENT_ENTITY_ALIASES = {"paymentmethod", "paymentmethods", "payment_method", "payment_methods"}


def _iter_entities(plan: dict):
    ents = (plan or {}).get("entities") or {}
    if isinstance(ents, dict):
        for k, v in ents.items():
            yield k, (v if isinstance(v, dict) else {})
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                yield e.get("name", ""), e


def detect_payment_intent(plan: dict) -> dict:
    """Return ``{"needs_payment_methods": bool, "reason": str}`` — planner
    precedence + two structural fallbacks (PaymentMethod entity, commerce
    flag). No regex/vocabulary sweeps."""
    if not plan:
        return {"needs_payment_methods": False, "reason": "no signal"}

    # 1. Planner-authored intent wins.
    saw_explicit_flag = False
    for name, info in _iter_entities(plan):
        v = info.get("needs_payment_methods")
        if v is True:
            return {"needs_payment_methods": True, "reason": f"planner:{name}"}
        if v is False:
            saw_explicit_flag = True
    if saw_explicit_flag:
        # Every entity that had the flag said False. Treat as opt-out — the
        # planner has explicitly silenced the auto-emit.
        return {"needs_payment_methods": False, "reason": "planner:opt-out"}

    # 2. Structural — planner declared a PaymentMethod entity outright.
    for name, _info in _iter_entities(plan):
        key = str(name or "").strip().lower().replace(" ", "_")
        if key in _PAYMENT_ENTITY_ALIASES:
            return {"needs_payment_methods": True, "reason": f"entity:{name}"}

    # 3. Commerce flag — cart-primitive path also needs saved cards.
    for name, info in _iter_entities(plan):
        if info.get("commerce") is True:
            return {"needs_payment_methods": True, "reason": f"commerce:{name}"}

    return {"needs_payment_methods": False, "reason": "no signal"}


# ── emission ───────────────────────────────────────────────────────────


_LIST_PAGE_ROUTE = "/settings/payment-methods"
_LIST_PAGE_FILE = ("settings", "payment-methods.json")
_NEW_PAGE_ROUTE = "/settings/payment-methods/new"
_NEW_PAGE_FILE = ("settings", "payment-methods", "new.json")


def _load_plan(root: Path) -> dict:
    for candidate in ("plan.json", "contracts/seed-plan.json"):
        p = root / candidate
        if not p.exists():
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("[payment-feature] plan read failed: %s", p)
    return {}


def _build_list_page() -> dict:
    return {
        "dataSources": [
            {"name": "paymentMethods", "entity": "PaymentMethod", "op": "list"}
        ],
        "root": {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.6", "padding": "tokens.spacing.6"},
            "children": [
                {
                    "type": "Stack",
                    "props": {"gap": "tokens.spacing.2"},
                    "children": [
                        {"type": "Text", "props": {"text": "Payment methods",
                                                     "as": "h1",
                                                     "variant": "page-title"}},
                        {"type": "Text", "props": {"text": "Saved cards used for future charges.",
                                                     "variant": "body",
                                                     "color": "muted-foreground"}},
                    ],
                },
                {
                    "type": "Card",
                    "props": {"padding": "tokens.spacing.4"},
                    "children": [
                        {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.4"},
                            "children": [
                                {
                                    "type": "Stack",
                                    "props": {"direction": "row",
                                              "justify": "between",
                                              "align": "center"},
                                    "children": [
                                        {"type": "Text", "props": {"text": "Your cards",
                                                                     "variant": "section-title"}},
                                        {"type": "Button", "props": {"label": "Add payment method",
                                                                       "navigate": _NEW_PAGE_ROUTE,
                                                                       "variant": "primary"}},
                                    ],
                                },
                                {
                                    "type": "Table",
                                    "props": {
                                        "columns": [
                                            {"key": "cardBrand", "label": "Brand"},
                                            {"key": "cardLast4", "label": "Last 4"},
                                            {"key": "isDefault", "label": "Default"},
                                        ],
                                        "rows": "{{paymentMethods}}",
                                        "emptyText": "No cards saved yet.",
                                        "rowActions": [{"label": "Remove",
                                                         "workflow": "DeletePaymentMethod",
                                                         "variant": "danger"}],
                                    },
                                },
                            ],
                        }
                    ],
                },
            ],
        },
    }


def _build_add_page() -> dict:
    return {
        "root": {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.6", "padding": "tokens.spacing.6"},
            "children": [
                {"type": "Text", "props": {"text": "Add payment method",
                                             "as": "h1",
                                             "variant": "page-title"}},
                {
                    "type": "Card",
                    "props": {"padding": "tokens.spacing.4"},
                    "children": [
                        {
                            "type": "Form",
                            "props": {"workflow": "CreatePaymentMethod",
                                      "submitLabel": "Save card"},
                            "children": [
                                {
                                    "type": "Stack",
                                    "props": {"gap": "tokens.spacing.4"},
                                    "children": [
                                        {"type": "Input", "props": {"name": "cardBrand",
                                                                      "label": "Brand",
                                                                      "placeholder": "Visa",
                                                                      "validators": {"required": True}}},
                                        {"type": "Input", "props": {"name": "cardLast4",
                                                                      "label": "Last 4",
                                                                      "placeholder": "4242",
                                                                      "validators": {"required": True,
                                                                                     "maxLength": 4}}},
                                        {"type": "Input", "props": {"name": "stripePaymentMethodId",
                                                                      "label": "Stripe payment method id",
                                                                      "placeholder": "pm_..."}},
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    }


def _write_if_absent(path: Path, payload: dict) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _register_in_nav_flow(root: Path) -> bool:
    nav_path = root / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return False
    try:
        nav = json.loads(nav_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("[payment-feature] nav-flow read failed")
        return False
    pages = nav.get("pages")
    if not isinstance(pages, list):
        pages = []
        nav["pages"] = pages
    existing = {p.get("route") for p in pages if isinstance(p, dict)}
    changed = False
    for route, page_id, shell in (
        (_LIST_PAGE_ROUTE, "settings-payment-methods", True),
        (_NEW_PAGE_ROUTE, "settings-payment-methods-new", True),
    ):
        if route in existing:
            continue
        pages.append({"id": page_id, "route": route, "shell": shell})
        changed = True
    if changed:
        try:
            nav_path.write_text(json.dumps(nav, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("[payment-feature] nav-flow write failed")
            return False
    return changed


def ensure_payment_surface(output_dir: str | Path) -> dict[str, Any]:
    """Emit the payment-methods list + add pages and register them in the
    nav flow when the plan says a payment surface is needed. Idempotent —
    never overwrites LLM-authored pages. Silent on unexpected errors.
    """
    summary: dict[str, Any] = {"surfaces_emitted": 0, "reason": "", "nav_updated": False}
    root = Path(output_dir)
    plan = _load_plan(root)
    intent = detect_payment_intent(plan)
    summary["reason"] = intent["reason"]
    if not intent["needs_payment_methods"]:
        return summary

    schemas_root = root / "src" / "schemas"
    list_path = schemas_root.joinpath(*_LIST_PAGE_FILE)
    new_path = schemas_root.joinpath(*_NEW_PAGE_FILE)

    try:
        if _write_if_absent(list_path, _build_list_page()):
            summary["surfaces_emitted"] += 1
    except Exception:  # noqa: BLE001
        logger.exception("[payment-feature] list page write failed")

    try:
        if _write_if_absent(new_path, _build_add_page()):
            summary["surfaces_emitted"] += 1
    except Exception:  # noqa: BLE001
        logger.exception("[payment-feature] new page write failed")

    try:
        summary["nav_updated"] = _register_in_nav_flow(root)
    except Exception:  # noqa: BLE001
        logger.exception("[payment-feature] nav registration failed")

    if summary["surfaces_emitted"] > 0:
        logger.info("[payment-feature] emitted %d surface(s) (%s), nav_updated=%s",
                    summary["surfaces_emitted"], summary["reason"], summary["nav_updated"])
    return summary

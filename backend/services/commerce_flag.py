"""Flag the one entity that acts as the "product" so downstream deterministic
builders can auto-place cart controls (AddToCart / CartBadge / CartPage,
per the cart runtime primitive at ``templates/runtime/db/forge-cart.schema.ts``).

Precedence:
  0. Any entity already carries ``commerce: True`` — respected verbatim (the
     planner or a previous pass owns the choice).
  1. Otherwise, backstop detection: if ``plan.commerce_intent`` is True (or,
     absent that, the brief/domain metadata mentions a commerce verb), pick
     one entity to flag — canonical product noun first, else the first
     primary-ish non-user/non-order entity.

Idempotent + additive: never removes an existing commerce flag, and only ONE
entity is ever flagged (the cart primitive is per-app, not per-catalogue).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Words in the brief/domain that unambiguously say "customers pay".
_COMMERCE_VERBS = {
    "sell", "sells", "selling", "sold",
    "buy", "buys", "buying", "bought",
    "purchase", "purchases", "purchasing", "purchased",
    "cart", "checkout", "storefront", "marketplace",
    "shop", "shopping", "shopper", "shoppers",
    "customer", "customers",
    "e-commerce", "ecommerce", "e commerce",
    "order", "orders", "place an order", "place order",
    "add to cart", "buy now",
}

# Canonical entity names strongly implying a saleable item.
_PRODUCT_ENTITY_NAMES = {
    "product", "item", "listing", "sku", "merchandise",
    "good", "goods", "ware", "wares", "catalog",
    "offering", "package", "bundle", "plan",
}

# Never auto-flag these — they're never the "saleable thing".
_SKIP_ENTITY_NAMES = {
    "user", "users", "role", "roles", "auth", "session", "sessions",
    "order", "orders", "cart", "cartitem", "cart_item", "invoice",
    "invoices", "payment", "payments", "notification", "notifications",
    "audit", "audits", "auditlog", "audit_log", "log", "logs",
}


def _brief_text(plan: dict) -> str:
    """Concatenate every free-text metadata field so vocabulary lookups don't
    care which key the caller populated."""
    parts: list[str] = []
    for key in ("brief", "description", "domain", "name", "prompt", "summary", "goal"):
        v = plan.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    sb = plan.get("structured_brief") or plan.get("structuredBrief") or {}
    if isinstance(sb, dict):
        for key in ("summary", "description", "elevator_pitch", "goal", "notes"):
            v = sb.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return " ".join(parts).lower()


def _has_commerce_vocab(text: str) -> bool:
    if not text:
        return False
    for phrase in _COMMERCE_VERBS:
        if " " in phrase:
            if phrase in text:
                return True
        elif re.search(rf"\b{re.escape(phrase)}\b", text):
            return True
    return False


def detect_commerce_intent(plan: dict) -> bool:
    """Return True when this plan should have a cart surface.

    Precedence: planner-authored ``plan.commerce_intent`` wins (True forces on,
    False forces off). Otherwise fall back to a brief/domain vocabulary sweep.
    """
    if isinstance(plan, dict):
        pi = plan.get("commerce_intent")
        if pi is True:
            return True
        if pi is False:
            return False
    return _has_commerce_vocab(_brief_text(plan))


def _pick_product_entity(entities: dict[str, dict]) -> str | None:
    """Canonical product noun first, else first non-skip entity in insertion
    order. Returns None on empty."""
    if not entities:
        return None
    for name in entities:
        if str(name).lower() in _PRODUCT_ENTITY_NAMES:
            return name
    for name in entities:
        if str(name).lower() in _SKIP_ENTITY_NAMES:
            continue
        return name
    return None


def flag_commerce_entity(plan: dict) -> dict:
    """If commerce intent is detected, mark the best-fit entity with
    ``commerce: true``. Idempotent — never clears an existing flag, and if
    ANY entity is already flagged the plan is returned unchanged.
    """
    entities = plan.get("entities")
    if not isinstance(entities, dict) or not entities:
        return plan

    # Planner-precedence: if any entity already carries commerce:True, we
    # trust that choice — no backstop, no override.
    for spec in entities.values():
        if isinstance(spec, dict) and spec.get("commerce") is True:
            return plan

    if not detect_commerce_intent(plan):
        return plan

    target = _pick_product_entity(entities)
    if not target:
        return plan
    spec = entities.get(target)
    if not isinstance(spec, dict):
        return plan

    spec["commerce"] = True
    logger.info("commerce_flag: marked entity %s as commerce", target)
    return plan

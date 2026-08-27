"""Auto-derivation of common ``interaction`` blocks from field-name +
FK conventions. Runs as a post-plan pass: the LLM authors any
interactions it noticed; we deterministically fill in obvious ones
it missed (invoice `total = quantity * unitPrice`, geo cascades, salary
components, timestamp `age`, etc.).

Two rules of the road:
  1. NEVER overwrite an existing ``interaction`` block — the LLM knew
     something we don't.
  2. Validate every derivation via :mod:`services.interaction_spec`
     before writing. If validation fails (e.g. sibling name we guessed
     wasn't actually a sibling), skip the derivation — better to under-
     derive than to author a broken interaction.

Public API::

    apply_auto_derivations(plan) -> {"applied": [...], "skipped": [...]}
        mutates plan['pages'][…]['fields'] in place; returns a report.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from services.interaction_spec import validate_interaction

logger = logging.getLogger(__name__)


# ── Field-name matchers ───────────────────────────────────────────────────
# Whole-word, case-insensitive. Ordered by specificity (multi-word first).

def _match(names: Iterable[str], patterns: Iterable[str]) -> str | None:
    """Return the first field name that matches any pattern. Patterns
    are regex fragments matched case-insensitively against the whole
    identifier (camelCase-friendly: `basicSalary` matches `basic`)."""
    for pat in patterns:
        rx = re.compile(rf"(^|[_-])?({pat})(?:$|[a-z_-])", re.IGNORECASE)
        for n in names:
            # camelCase: strip the trailing lowercase word to normalise.
            if rx.search(n) or n.lower() == pat.lower():
                return n
            # Match on token boundary within camelCase.
            tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", n)
            if any(t.lower() == pat.lower() for t in tokens):
                return n
    return None


def _find_sibling(names: Iterable[str], *patterns: str) -> str | None:
    return _match(names, patterns)


# ── Individual rule implementations ────────────────────────────────────────


def _rule_line_total(field: dict, siblings: list[dict]) -> dict | None:
    """`total`/`lineTotal` = quantity × price when both siblings exist."""
    name = field.get("name", "")
    if not re.search(r"(^|[A-Z_-])(total|lineTotal|amount|extended)$", name, re.I):
        return None
    if name.lower() in {"grandtotal", "subtotal"}:
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    qty = _find_sibling(names, "quantity", "qty")
    price = _find_sibling(names, "unitPrice", "price", "rate", "unitCost")
    if not qty or not price or qty == name or price == name:
        return None
    return {"computed": {"formula": f"{qty} * {price}", "readOnly": True}}


def _rule_subtotal_from_lines(field: dict, siblings: list[dict]) -> dict | None:
    """`subtotal` = sum of a `lines[]` array's totals — placeholder for
    arrayField future. Today, we skip because we don't have array-field
    context; kept as a marker so the rule ordering stays coherent."""
    return None  # deferred to Category-8 arrayField primitive


def _rule_grand_total(field: dict, siblings: list[dict]) -> dict | None:
    """`grandTotal` = subtotal + tax − discount."""
    name = field.get("name", "")
    if not re.fullmatch(r"grandTotal|grandtotal|total", name, re.I):
        # `total` is ambiguous — only take it when we also see subtotal.
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    sub = _find_sibling(names, "subtotal", "subTotal")
    if not sub:
        return None
    tax = _find_sibling(names, "tax", "taxAmount", "gst", "vat")
    disc = _find_sibling(names, "discount", "discountAmount")
    parts = [sub]
    if tax: parts.append(f"+ {tax}")
    if disc: parts.append(f"- {disc}")
    if len(parts) == 1:
        return None  # subtotal alone doesn't warrant grand-total
    formula = " ".join([parts[0], *parts[1:]])
    return {"computed": {"formula": formula, "readOnly": True}}


def _rule_hra_from_basic(field: dict, siblings: list[dict]) -> dict | None:
    """`hra` = basic × 0.40 (Indian payroll default; conservative)."""
    name = field.get("name", "")
    if not re.fullmatch(r"hra|houseRentAllowance", name, re.I):
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    basic = _find_sibling(names, "basicSalary", "basic", "basicPay")
    if not basic:
        return None
    return {"computed": {"formula": f"{basic} * 0.4", "readOnly": True}}


def _rule_da_from_basic(field: dict, siblings: list[dict]) -> dict | None:
    """`da` (Dearness Allowance) = basic × 0.12."""
    name = field.get("name", "")
    if not re.fullmatch(r"da|dearnessAllowance", name, re.I):
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    basic = _find_sibling(names, "basicSalary", "basic", "basicPay")
    if not basic:
        return None
    return {"computed": {"formula": f"{basic} * 0.12", "readOnly": True}}


def _rule_age_from_dob(field: dict, siblings: list[dict]) -> dict | None:
    """`age` = age(dob) — uses the runtime age() helper."""
    name = field.get("name", "")
    if not re.fullmatch(r"age", name, re.I):
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    dob = _find_sibling(names, "dob", "dateOfBirth", "birthDate", "birthday")
    if not dob:
        return None
    return {"computed": {"formula": f"age({dob})", "readOnly": True}}


def _rule_duration_days(field: dict, siblings: list[dict]) -> dict | None:
    """`days`/`duration` = daysBetween(startDate, endDate)."""
    name = field.get("name", "")
    if not re.fullmatch(r"days|duration|nights|numberOfDays", name, re.I):
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    start = _find_sibling(names, "startDate", "checkIn", "fromDate", "from")
    end = _find_sibling(names, "endDate", "checkOut", "toDate", "to")
    if not start or not end:
        return None
    return {"computed": {"formula": f"daysBetween({start}, {end})", "readOnly": True}}


def _rule_state_cascades_from_country(field: dict, siblings: list[dict]) -> dict | None:
    """State FK depends on Country FK — auto-emit optionsFrom.filter.

    Conservative — only when both fields end in `Id` (real FKs) and we
    have visible country + state siblings. The `source`/`value`/`label`
    are best-effort ("states"/"id"/"name"); validator rejects if the
    resource doesn't exist and we skip.
    """
    name = field.get("name", "")
    if not re.fullmatch(r"stateId|state_id|state", name, re.I):
        return None
    names = [s.get("name") for s in siblings if isinstance(s, dict) and s.get("name")]
    country = _find_sibling(names, "countryId", "country_id", "country")
    if not country:
        return None
    return {
        "optionsFrom": {
            "source": "states",
            "value": "id",
            "label": "name",
            "filter": {"countryId": f"{{{{{country}}}}}"},
        }
    }


# Rule dispatch order — first match wins per field. Ordered by specificity
# so `grandTotal` beats `total` beats `lineTotal`.
_RULES = [
    _rule_grand_total,
    _rule_hra_from_basic,
    _rule_da_from_basic,
    _rule_age_from_dob,
    _rule_duration_days,
    _rule_state_cascades_from_country,
    _rule_line_total,
    _rule_subtotal_from_lines,
]


# ── Entry point ───────────────────────────────────────────────────────────


def apply_auto_derivations(
    plan: dict[str, Any],
    registry: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Walk every page's fields; for each field WITHOUT an interaction
    block, run rules in order and apply the first that produces a
    validator-accepted result.

    Returns a report ``{applied: [...], skipped: [...]}`` for logging /
    telemetry. Idempotent — running twice is a no-op.
    """
    applied: list[str] = []
    skipped: list[str] = []

    pages = plan.get("pages")
    if not isinstance(pages, list):
        return {"applied": applied, "skipped": skipped}

    for page in pages:
        if not isinstance(page, dict):
            continue
        fields = page.get("fields")
        if not isinstance(fields, list):
            continue
        page_id = str(page.get("id") or page.get("route") or "?")

        for field in fields:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not isinstance(name, str):
                continue
            # Rule of the road #1 — never overwrite a hand-authored block.
            if field.get("interaction"):
                continue

            for rule in _RULES:
                try:
                    proposal = rule(field, fields)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[interaction_auto_derive] %s crashed on %s: %s",
                                 rule.__name__, name, exc)
                    continue
                if not proposal:
                    continue
                # Rule of the road #2 — validate before writing.
                result = validate_interaction(proposal, field, fields, registry=registry)
                if not result.ok:
                    skipped.append(f"{page_id}.{name} via {rule.__name__}: {result.errors[0] if result.errors else 'invalid'}")
                    continue
                field["interaction"] = result.canonical
                applied.append(f"{page_id}.{name} via {rule.__name__}")
                break  # first-rule-wins semantics

    return {"applied": applied, "skipped": skipped}

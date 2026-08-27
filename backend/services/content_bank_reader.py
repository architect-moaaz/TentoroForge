"""Spec C3 — Content bank reader.

Downstream emitters (empty-states, toast copy, notification templates,
form CTA labels) ask this module for their strings. The brief's
``content_bank`` is the authority; when a key is missing or the whole
bank is absent, the caller's own generic-CRUD default (from
``deterministic_strings``) still ships — nothing crashes.

Substitution vocabulary (any string may include these):
    {entity_singular}   — "invoice"
    {entity_plural}     — "invoices"
    {query}             — user's current search text
    {task_kind}         — "approval", "review", …
    {app_name}          — from project settings

Unknown tokens are left in place so a mis-spelled key surfaces as
literal ``{typo}`` in the UI instead of vanishing silently.
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _lookup(bank: Any, section: str, key: str) -> str | None:
    """Return the raw template string for ``bank.section.key`` or None.

    Accepts either a ``ContentBank`` pydantic model or a plain dict
    (post-loading from JSON), so callers don't have to hydrate.
    """
    if bank is None:
        return None
    # Pydantic model path
    sect = getattr(bank, section, None)
    if sect is None and isinstance(bank, dict):
        sect = bank.get(section)
    if not isinstance(sect, dict):
        return None
    val = sect.get(key)
    return val if isinstance(val, str) and val else None


def substitute(template: str, subs: dict[str, str] | None) -> str:
    """Replace ``{token}`` placeholders in ``template`` with values from
    ``subs``. Unknown tokens are left intact."""
    if not template or not subs:
        return template
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        v = subs.get(key)
        return v if isinstance(v, str) else m.group(0)
    return _TOKEN_RE.sub(_sub, template)


def get_string(
    bank: Any,
    section: str,
    key: str,
    fallback: str,
    subs: dict[str, str] | None = None,
) -> str:
    """Look up ``bank.section.key`` and template-substitute ``subs``.

    Falls back to ``fallback`` (also substituted) when the bank is
    silent. This is the ONE call site every emitter uses so voice
    consistency is easy to reason about.
    """
    tpl = _lookup(bank, section, key) or fallback
    return substitute(tpl, subs)


# --------------------------------------------------------------------------- #
# Convenience readers by section — the actual entry points emitters use.
# --------------------------------------------------------------------------- #

def empty_state(
    bank: Any, kind: str, fallback: str, *, entity_singular: str = "",
    entity_plural: str = "", query: str = "",
) -> str:
    """``kind`` = list | search | filtered | first_use."""
    return get_string(
        bank, "empty_states", kind, fallback,
        {"entity_singular": entity_singular, "entity_plural": entity_plural,
         "query": query},
    )


def toast(
    bank: Any, kind: str, fallback: str, *, entity_singular: str = "",
    entity_plural: str = "",
) -> str:
    """``kind`` = created | updated | deleted | error_generic | error_permission."""
    return get_string(
        bank, "toasts", kind, fallback,
        {"entity_singular": entity_singular, "entity_plural": entity_plural},
    )


def notification(
    bank: Any, kind: str, fallback: str, *, entity_singular: str = "",
    task_kind: str = "",
) -> str:
    """``kind`` = task_assigned | approval_needed | ...  (open vocabulary)"""
    return get_string(
        bank, "notifications", kind, fallback,
        {"entity_singular": entity_singular, "task_kind": task_kind},
    )


def cta_verb(bank: Any, kind: str, fallback: str) -> str:
    """``kind`` = primary | create | delete | update | submit — the labeler
    the form scaffolder uses for submit buttons."""
    return get_string(bank, "cta_verbs", kind, fallback)


# --------------------------------------------------------------------------- #
# Meaningful-variation check — used by tests / QA to catch identical banks
# --------------------------------------------------------------------------- #

def fingerprint(bank: Any) -> str:
    """Return a short, order-independent fingerprint of a bank's copy so
    QA can flag two apps shipping the same content verbatim."""
    import hashlib
    if bank is None:
        return ""
    payload_parts: list[str] = []
    for section in ("empty_states", "toasts", "notifications", "cta_verbs"):
        sect = getattr(bank, section, None)
        if sect is None and isinstance(bank, dict):
            sect = bank.get(section)
        if not isinstance(sect, dict):
            continue
        for k in sorted(sect.keys()):
            v = sect.get(k)
            if isinstance(v, str) and v.strip():
                payload_parts.append(f"{section}:{k}={v.strip()}")
    if not payload_parts:
        return ""
    return hashlib.md5("|".join(payload_parts).encode("utf-8")).hexdigest()[:12]


__all__ = [
    "cta_verb", "empty_state", "fingerprint", "get_string",
    "notification", "substitute", "toast",
]

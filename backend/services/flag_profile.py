"""One place for every FORGE_* on/off feature gate to be resolved.

Before this module, ~60 gates each read ``os.getenv("FORGE_X")`` with their
own truthiness convention. Turning "everything on" meant flipping 60 env
vars; nobody could remember which ones were needed for a good app.

This module introduces a single meta-flag:

* ``FORGE_QUALITY=full`` — every ``is_on(...)`` call returns True.
* ``FORGE_QUALITY=off``  — every ``is_on(...)`` call returns False.
* ``FORGE_QUALITY`` unset (or set to anything else) — fall through to the
  per-flag env var with the caller's ``default``.

Individual FORGE_* flags remain callable escape hatches for debugging a
single gate. In day-to-day use, set ``FORGE_QUALITY=full`` once and be done.

Scope: BINARY feature gates only. Non-binary flags (e.g.
``FORGE_JOURNEY_GATE=off|warn|strict``) and CONFIG values (URLs, model
names, timeouts) must NOT be routed through here — they don't fit the
on/off contract and losing their custom semantics would be a regression.
"""
from __future__ import annotations

import os

_TRUTHY = ("1", "true", "yes", "on")
_QUALITY_ENV = "FORGE_QUALITY"


def is_on(name: str, *, default: bool = False) -> bool:
    """Return whether the named FORGE_* gate is enabled.

    Args:
        name: The env-var name (e.g. ``"FORGE_SELF_VERIFY"``).
        default: Value to use when ``name`` is unset and no ``FORGE_QUALITY``
            override applies.

    NOTE: :mod:`services.flag_manifest` documents every gate and its state,
    but deliberately does NOT feed this function. Making the manifest
    authoritative over ``default`` was tried and reverted: an inferred
    default disagrees with what call sites actually pass, in both
    directions, and silently moved Smith, self-verify and ~25 other
    behaviours. Reconciling a gate's default with its declaration is a
    per-gate decision someone makes on purpose, not something to derive.
    """
    quality = (os.environ.get(_QUALITY_ENV) or "").strip().lower()
    if quality == "full":
        return True
    if quality == "off":
        return False
    # Any other value (unset, "partial", typo) → fall through.
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY

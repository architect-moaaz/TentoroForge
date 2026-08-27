"""Deterministic per-app variance seed.

Two apps with the SAME brief (identical description + module name)
must get the SAME seed so re-generation is reproducible. Two apps with
DIFFERENT briefs must get DIFFERENT seeds so their moment/signature
picks diverge — the whole point of Phase 2 is that "two yoga studios"
should not collapse to the same page.

The seed is a stable 32-bit integer. LLM-authored decision phases
include it in their user prompt as a "VARIANCE HINT" — the LLM uses
it to break ties when otherwise indistinguishable choices exist
(which signature-move to prefer, which hero kind to reach for, which
of two equivalent chart shapes to pick).

Design notes:

- **Not a nonce.** The seed is stable per-brief. It must not include
  timestamps or wall-clock state, or re-generation reproducibility
  breaks.
- **Not a secret.** It's a plain int the LLM sees. No security value.
- **Deterministic.** ``variance_seed_for(same-plan)`` always returns
  the same value across processes / hosts / Python versions (we use
  ``hashlib.blake2b`` — stable across CPython versions).
- **Salt-free.** No env-configurable salt — that would break the
  reproducibility contract and add a flag we don't need.
"""
from __future__ import annotations

import hashlib
from typing import Any


# Bit-width of the emitted seed. 32 bits gives ~4B distinct seeds —
# plenty for "two same-domain apps diverge" and small enough to fit
# comfortably in an LLM prompt line without looking noisy.
_SEED_BITS = 32
_SEED_MASK = (1 << _SEED_BITS) - 1


def variance_seed_for(plan: dict[str, Any] | None) -> int:
    """Deterministic per-plan variance seed.

    Reads the plan's identity fields (description / brief / module_name)
    and hashes them into a stable 32-bit integer. Never raises — a
    non-dict / empty plan returns 0 (the LLM treats "no hint" the same
    as any other value; behavior stays deterministic).

    The seed is intentionally **not** salted by env or timestamp — that
    would break the reproducibility contract this module exists for.
    """
    if not isinstance(plan, dict):
        return 0

    # Priority order for the "identity text" we hash. The planner's
    # LLM description is the most stable — module_name and appName
    # sometimes get renamed post-authoring (branding lock, user edits).
    parts: list[str] = []
    for key in ("description", "brief", "prompt", "module_name", "appName", "name"):
        v = plan.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(f"{key}={v.strip()}")

    if not parts:
        return 0

    # blake2b is deterministic across CPython versions, unlike Python's
    # builtin hash() which is PYTHONHASHSEED-salted per-process.
    h = hashlib.blake2b("\n".join(parts).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") & _SEED_MASK


def variance_hint_line(plan: dict[str, Any] | None) -> str:
    """One-line prompt fragment describing the variance seed.

    Prompt-facing wrapper around :func:`variance_seed_for`. Callers
    embed the return value in the LLM's user prompt so the model can
    key its tiebreaks off it.

    Empty string when the plan has no hashable identity — the LLM
    then behaves as before (no hint, default tiebreaks).
    """
    seed = variance_seed_for(plan)
    if seed == 0:
        return ""
    return (
        f"VARIANCE HINT (seed={seed}): when two design choices are "
        "otherwise equivalent (e.g. two signature-move ids that both "
        "fit the brief, two hero kinds that both suit the domain), "
        "use this seed as a tiebreak so this app's picks diverge from "
        "other same-domain apps generated with different briefs."
    )

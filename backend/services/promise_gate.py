"""SV-STRICT-4 — deterministic promise-vs-delivery gate.

Given the app's ComponentContracts + Promises, return synthetic
:data:`FaultSignature.PROMISE_NOT_DELIVERED` entries (in the same JSON
shape the runner emits) for every persona job that has no reachable
component plausibly fulfilling it.

This is the *gen-time* verifier for the ``why`` slot — no browser, no
Playwright. Runs at pipeline end and supplements the runtime
interaction-driven faults.

Design principles
-----------------

* Pure function. No I/O. No LLM.
* "Plausibly fulfills" uses cheap word-token matching between the job
  label / primary_entities and each contract's label / route /
  component_type. Deliberately liberal — false-positives (real
  fulfillments we missed) are worse than false-negatives (spurious
  promise faults). Slice 5's fault log will accumulate false-positive
  rates so future work can tighten the matcher.
* Synthetic-fault shape matches what the runner emits so the narrator
  and the classifier work on it unchanged.
"""
from __future__ import annotations

import re
from typing import Any

from services.blueprint_promises import PersonaJob, Promises
from services.component_contract import ComponentContract
from services.fault_classifier import FaultSignature


_WORD_RE = re.compile(r"[a-z0-9]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in",
    "my", "your", "their", "some", "any", "all", "with",
    "is", "are", "be", "do", "does",
}


def check_promises(
    contracts: list[ComponentContract],
    promises: Promises,
) -> list[dict[str, Any]]:
    """Return a synthetic fault list for unfulfilled persona jobs.

    Each entry is shaped like the runner's raw fault dict so the rest
    of the pipeline (classifier + narrator + summary) needs no special
    case for these.
    """
    faults: list[dict[str, Any]] = []
    for job in promises.persona_jobs or []:
        if _fulfilled_by(contracts, job):
            continue
        faults.append(_synthetic_fault(job))
    return faults


# ── Fulfillment heuristic ────────────────────────────────────────────────


def _fulfilled_by(contracts: list[ComponentContract], job: PersonaJob) -> bool:
    """True when some contract plausibly delivers the job.

    Match rule: exact token equality on singularized forms. A job about
    ``cancellation`` no longer matches a page about ``bookings`` just
    because ``cancel`` is a substring of ``cancellation`` and ``book`` a
    substring of ``booking`` — the old ``stem-intersect`` was too permissive
    and silently swallowed real gaps. Singularization catches the one
    legitimate case (Session ↔ sessions) without opening the substring door.
    """
    job_tokens = _normalize(_tokenize(job.job_label))
    entity_tokens: set[str] = set()
    for ent in job.primary_entities:
        entity_tokens.update(_normalize(_tokenize(ent)))

    for c in contracts:
        if c.component_type not in ("page", "workflow", "detail"):
            continue
        haystack = " ".join([c.label or "", c.route or "", c.id or ""])
        hs_tokens = _normalize(_tokenize(haystack))
        if entity_tokens and (entity_tokens & hs_tokens):
            return True
        if job_tokens and (job_tokens & hs_tokens):
            return True
    return False


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    # Split camelCase (`BookClass` → `Book Class`) so identifiers match
    # natural-language job labels.
    normalized = _CAMEL_SPLIT_RE.sub(" ", text)
    words = set(_WORD_RE.findall(normalized.lower()))
    return {w for w in words if w not in _STOP and len(w) > 2}


def _normalize(tokens: set[str]) -> set[str]:
    """Collapse trivial plural forms so ``sessions`` matches ``session``.

    Deliberately conservative — only the three regular English plural
    suffixes (``ies → y``, ``es → e``, ``s → ``). No stemming, no
    substring: ``bookings`` normalizes to ``booking`` but ``cancellation``
    stays ``cancellation`` and won't match.
    """
    out: set[str] = set()
    for t in tokens:
        out.add(_singularize(t))
    return out


def _singularize(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"          # bookings→booking not affected; policies→policy
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]                 # classes→class
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]                 # sessions→session, bookings→booking
    return word


# ── Synthetic fault shape ────────────────────────────────────────────────


def _synthetic_fault(job: PersonaJob) -> dict[str, Any]:
    """Build a runner-compatible fault dict for an unfulfilled job.

    ``interaction`` masquerades as a ``route`` interaction whose ``id``
    encodes the persona+job. Downstream classifier + narrator handle
    it without special-casing.
    """
    sid = f"promise:{job.persona_id}:{job.job_id or _slug(job.job_label)}"
    return {
        "interaction_id": sid,
        "interaction": {
            "kind": "route",
            "id": sid,
            "route": f"promise://{job.persona_id}/{job.job_id or _slug(job.job_label)}",
            "requires_auth": False,
            "label": job.job_label,
        },
        "evidence": {
            "status": None,
            "body_excerpt": (
                f"No component fulfills the persona job "
                f"'{job.job_label}' for {job.persona_name}."
            ),
        },
        # Pre-classified — the gate is deterministic, no re-run needed.
        # Downstream (verify_summary + narrator) reads these fields
        # directly the same way it reads classifier output.
        "signature": FaultSignature.PROMISE_NOT_DELIVERED,
        "priority": "BROKEN",
        "layer": "value",
        "w_slot": "why",
        "hypothesis": (
            "The product brief promised this job but no page or "
            "workflow was generated to serve it."
        ),
        "_synthetic": True,
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "job"

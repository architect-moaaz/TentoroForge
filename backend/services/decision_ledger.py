"""Decision ledger — Slice REL-S1.

Every emitter that today silently picks between valid alternatives
(button→workflow, form→submit, FK→entity, archetype→vocab) records
its pick here with confidence + the alternatives it considered.

Two artifacts land on disk per generation:

- ``open_decisions.json`` — the raw ledger. All decisions, all
  confidence bands. Sink for auditing + chip surfacing.
- ``bindings.json`` — the "confirmed picks" that fed the next
  generation. Emitters check this FIRST before running their
  ambiguity logic; a matching entry short-circuits the pick.

**Confidence contract** (uniform across all emitters):

- ``high``   (≥0.9): exact-name match on a single candidate. Ships
  silently — the ledger records it but no chip surfaces.
- ``medium`` (0.6-0.9): fuzzy/substring match, OR exact match with
  a runner-up close behind. Ships but chip surfaces so user can swap.
- ``low``    (<0.6): multiple plausible candidates, no strong
  winner. Ships with the top pick (never fails the build) BUT
  chip surfaces prominently and repair should be considered pending
  until confirmed.

The chosen band decides whether the pick is "held" for user
confirmation or ships silently. The user's confirmation writes to
``bindings.json``.

**Bindings key.** ``(scope, kind, identity)`` — e.g.
``("page:/documents/upload", "form_submit", "UploadDocumentForm")``.
Any component of the tuple missing → binding won't match, and the
emitter falls back to its ambiguity logic. This auto-invalidates
picks when the underlying schema renames the identity.

Fail-open: any I/O error keeps generation running with the pick
that would have been made anyway; the artifact write is best-effort.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# Confidence bands
# ══════════════════════════════════════════════════════════════════

BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_LOW = "low"

# Numeric thresholds — inclusive-of-lower-bound, exclusive-of-upper.
# Emitters that score by float can call :func:`band_for_score` to
# stay consistent; emitters that only know "matched" or "guessed"
# can pass the band string directly.
BAND_HIGH_MIN = 0.9
BAND_MEDIUM_MIN = 0.6


def band_for_score(score: float) -> str:
    """Map a 0..1 score to one of the three band strings.

    Emitters typically already score candidates (see
    ``orphan_wiring_pass._score_form_for_workflow``); this keeps the
    band assignment uniform across the pipeline instead of every
    emitter picking its own thresholds.
    """
    if score >= BAND_HIGH_MIN:
        return BAND_HIGH
    if score >= BAND_MEDIUM_MIN:
        return BAND_MEDIUM
    return BAND_LOW


# ══════════════════════════════════════════════════════════════════
# Decision shape
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Alternative:
    """One candidate the emitter considered but didn't pick."""
    target: str
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    """One pick an emitter made between alternatives.

    ``decision_id`` is a stable, content-derived slug so re-runs
    that make the same pick don't create duplicate chip records.
    Format: ``{kind}:{scope}:{identity}``, all lower-kebab.

    ``kind`` is the well-known slug for what class of pick this is
    (button_target / form_submit / fk_target / archetype). Chip UI
    switches presentation on this.

    ``scope`` locates the pick in the app (route or workflow name);
    ``identity`` names the specific thing being wired (the button
    label, form name, column name).

    ``target_picked`` is the chosen target. ``alternatives`` is
    every other viable candidate the emitter considered (empty when
    the emitter had exactly one candidate — still recorded so audits
    can tell "high-confidence" apart from "no choice at all").

    ``confidence`` is the band the emitter assigned.
    ``source_emitter`` names the module that wrote the record — so
    logs and chip UIs can attribute the decision.
    """
    decision_id: str
    kind: str
    scope: str
    identity: str
    target_picked: str
    confidence: str
    source_emitter: str
    alternatives: tuple[Alternative, ...] = ()
    reason: str = ""


# ══════════════════════════════════════════════════════════════════
# Well-known kinds
# ══════════════════════════════════════════════════════════════════

KIND_BUTTON_TARGET = "button_target"
KIND_FORM_SUBMIT = "form_submit"
KIND_FK_TARGET = "fk_target"
KIND_ARCHETYPE = "archetype"

_ALLOWED_KINDS = frozenset({
    KIND_BUTTON_TARGET,
    KIND_FORM_SUBMIT,
    KIND_FK_TARGET,
    KIND_ARCHETYPE,
})


def _slug(s: str) -> str:
    """Lowercase kebab suitable for a decision-id fragment.

    Keeps route slashes readable (``/documents/upload`` →
    ``documents/upload``), collapses whitespace and non-word chars
    to hyphens. Length-bounded so decision_id doesn't blow logs.
    """
    if not s:
        return "unknown"
    import re
    out = re.sub(r"[^A-Za-z0-9/_\-]+", "-", str(s).strip().lower())
    return out.strip("-")[:80] or "unknown"


def make_decision_id(kind: str, scope: str, identity: str) -> str:
    """Build a stable decision-id from its (kind, scope, identity)
    tuple. Same inputs → same id, so re-emits are idempotent."""
    return f"{_slug(kind)}:{_slug(scope)}:{_slug(identity)}"


def make_alternative(target: str, score: float = 0.0, reason: str = "") -> Alternative:
    """Convenience constructor with float coercion."""
    return Alternative(target=str(target), score=float(score or 0.0), reason=str(reason or ""))


def make_decision(
    *,
    kind: str,
    scope: str,
    identity: str,
    target_picked: str,
    confidence: str,
    source_emitter: str,
    alternatives: Iterable[Alternative] | None = None,
    reason: str = "",
) -> Decision:
    """Build a Decision, validating kind + band strings.

    Raises ValueError on invalid kind/band — callers should treat
    these as programmer errors, not runtime edge cases.
    """
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unknown decision kind: {kind!r} (allowed: {sorted(_ALLOWED_KINDS)})")
    if confidence not in {BAND_HIGH, BAND_MEDIUM, BAND_LOW}:
        raise ValueError(
            f"unknown confidence band: {confidence!r} "
            f"(allowed: {BAND_HIGH!r}, {BAND_MEDIUM!r}, {BAND_LOW!r})"
        )
    alts = tuple(alternatives or ())
    return Decision(
        decision_id=make_decision_id(kind, scope, identity),
        kind=kind,
        scope=scope,
        identity=identity,
        target_picked=str(target_picked),
        confidence=confidence,
        source_emitter=source_emitter,
        alternatives=alts,
        reason=reason,
    )


# ══════════════════════════════════════════════════════════════════
# Ledger I/O — open_decisions.json (per project, cumulative per gen)
# ══════════════════════════════════════════════════════════════════

OPEN_DECISIONS_REL = ("src", "contracts", "open_decisions.json")
BINDINGS_REL = ("src", "contracts", "bindings.json")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write_json(path: Path, data: Any) -> Path | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("[decision-ledger] write failed %s: %s", path, exc)
        return None


def _decision_to_dict(d: Decision) -> dict[str, Any]:
    out = asdict(d)
    out["alternatives"] = [asdict(a) for a in d.alternatives]
    return out


def record(output_dir: str | Path, decision: Decision) -> Path | None:
    """Append (or update) a decision in ``open_decisions.json``.

    Idempotency: same ``decision_id`` overwrites the prior record
    for that pick. This handles re-runs of the same emitter cleanly
    without accumulating duplicates.
    """
    root = Path(output_dir)
    path = root.joinpath(*OPEN_DECISIONS_REL)
    ledger = _load_json(path, default={"generated_at": _iso_now(), "decisions": []})
    if not isinstance(ledger, dict):
        ledger = {"generated_at": _iso_now(), "decisions": []}
    decisions = ledger.get("decisions")
    if not isinstance(decisions, list):
        decisions = []

    new_row = _decision_to_dict(decision)
    # Overwrite same-id entry; append otherwise. Preserves order.
    replaced = False
    for i, row in enumerate(decisions):
        if isinstance(row, dict) and row.get("decision_id") == decision.decision_id:
            decisions[i] = new_row
            replaced = True
            break
    if not replaced:
        decisions.append(new_row)

    ledger["decisions"] = decisions
    ledger["generated_at"] = _iso_now()
    return _write_json(path, ledger)


def load_ledger(output_dir: str | Path) -> list[dict[str, Any]]:
    """Read the ledger. Empty list when the artifact is missing/broken."""
    path = Path(output_dir).joinpath(*OPEN_DECISIONS_REL)
    ledger = _load_json(path, default={})
    if not isinstance(ledger, dict):
        return []
    decisions = ledger.get("decisions")
    return decisions if isinstance(decisions, list) else []


def pending_decisions(output_dir: str | Path) -> list[dict[str, Any]]:
    """Return only decisions that surface as chips (medium/low).

    High-confidence picks stay silent — auditors can still read them
    via :func:`load_ledger`.
    """
    return [
        d for d in load_ledger(output_dir)
        if isinstance(d, dict) and d.get("confidence") in {BAND_MEDIUM, BAND_LOW}
    ]


# ══════════════════════════════════════════════════════════════════
# Bindings — confirmed picks feed the next generation
# ══════════════════════════════════════════════════════════════════

def _bindings_key(kind: str, scope: str, identity: str) -> str:
    """Compact key used inside bindings.json. Mirrors decision_id
    format so lookups are trivial."""
    return make_decision_id(kind, scope, identity)


def load_bindings(output_dir: str | Path) -> dict[str, str]:
    """Return the confirmed-pick map: {binding_key → target}.

    Empty when no bindings file exists yet. Emitters call
    :func:`resolve_binding` rather than this directly so the lookup
    keys stay consistent.
    """
    path = Path(output_dir).joinpath(*BINDINGS_REL)
    data = _load_json(path, default={})
    if not isinstance(data, dict):
        return {}
    bindings = data.get("bindings")
    if not isinstance(bindings, dict):
        return {}
    # Coerce values to str; drop non-string picks.
    return {
        str(k): str(v) for k, v in bindings.items()
        if isinstance(k, str) and isinstance(v, (str, int, float))
    }


def resolve_binding(
    output_dir: str | Path, *, kind: str, scope: str, identity: str,
) -> str | None:
    """Look up a confirmed pick. Returns None when no binding is
    recorded — caller then runs its normal ambiguity logic."""
    key = _bindings_key(kind, scope, identity)
    return load_bindings(output_dir).get(key)


def save_binding(
    output_dir: str | Path,
    *,
    kind: str,
    scope: str,
    identity: str,
    target: str,
) -> Path | None:
    """Persist a confirmed pick. Overwrites the same key silently
    (user swapping their choice after already confirming once).

    Also marks the matching entry in ``open_decisions.json`` as
    ``resolved: True`` so the chip UI stops surfacing it.
    """
    root = Path(output_dir)
    b_path = root.joinpath(*BINDINGS_REL)
    data = _load_json(b_path, default={"generated_at": _iso_now(), "bindings": {}})
    if not isinstance(data, dict):
        data = {"generated_at": _iso_now(), "bindings": {}}
    bindings = data.get("bindings")
    if not isinstance(bindings, dict):
        bindings = {}
    key = _bindings_key(kind, scope, identity)
    bindings[key] = str(target)
    data["bindings"] = bindings
    data["generated_at"] = _iso_now()
    written = _write_json(b_path, data)

    # Also mark resolved in the ledger so the chip stops surfacing.
    ledger_path = root.joinpath(*OPEN_DECISIONS_REL)
    ledger = _load_json(ledger_path, default={})
    if isinstance(ledger, dict) and isinstance(ledger.get("decisions"), list):
        touched = False
        for row in ledger["decisions"]:
            if isinstance(row, dict) and row.get("decision_id") == key:
                row["resolved"] = True
                row["resolved_target"] = str(target)
                row["resolved_at"] = _iso_now()
                touched = True
        if touched:
            _write_json(ledger_path, ledger)

    return written


# ══════════════════════════════════════════════════════════════════
# Convenience: single-call record + resolve
# ══════════════════════════════════════════════════════════════════

def record_pick(
    output_dir: str | Path,
    *,
    kind: str,
    scope: str,
    identity: str,
    target_picked: str,
    confidence: str | float,
    source_emitter: str,
    alternatives: Iterable[Alternative] | None = None,
    reason: str = "",
) -> Decision:
    """One-liner every emitter can call: builds the Decision,
    records it, returns it. Accepts a float score OR a band string
    for ``confidence``.

    Doesn't consult bindings.json — the emitter checks that FIRST
    (via :func:`resolve_binding`) before running its own picking
    logic, otherwise the ledger fills with picks made moot by the
    binding.
    """
    band = confidence if isinstance(confidence, str) else band_for_score(float(confidence))
    d = make_decision(
        kind=kind,
        scope=scope,
        identity=identity,
        target_picked=target_picked,
        confidence=band,
        source_emitter=source_emitter,
        alternatives=alternatives,
        reason=reason,
    )
    try:
        record(output_dir, d)
    except Exception as exc:  # noqa: BLE001
        # Ledger write failure is never fatal — the emitter still
        # ships the pick. Log so we notice repeated failures.
        logger.warning("[decision-ledger] record failed for %s: %s", d.decision_id, exc)
    return d


__all__ = [
    # Bands
    "BAND_HIGH", "BAND_MEDIUM", "BAND_LOW",
    "BAND_HIGH_MIN", "BAND_MEDIUM_MIN",
    "band_for_score",
    # Kinds
    "KIND_BUTTON_TARGET", "KIND_FORM_SUBMIT", "KIND_FK_TARGET", "KIND_ARCHETYPE",
    # Types
    "Alternative", "Decision",
    # Constructors
    "make_alternative", "make_decision", "make_decision_id",
    # Ledger I/O
    "OPEN_DECISIONS_REL", "BINDINGS_REL",
    "record", "record_pick", "load_ledger", "pending_decisions",
    # Bindings
    "load_bindings", "resolve_binding", "save_binding",
]

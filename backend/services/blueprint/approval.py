"""Whether the user has authorised what is about to happen (PRD §25, §95, §76).

This is the Blueprint's own view of consent, and it lives here rather than in
:mod:`services.smith` for a layering reason that turned out to be a design
reason too.

``approvals`` is a Blueprint section, and the fingerprint an approval is taken
against is computed from Blueprint sections. Smith *presents* a gate and
*records* the answer — those are conversation — but "has this been authorised,
and is that authorisation still true" is a question the document can answer
about itself. The orchestrator has to ask it before it builds, and the
orchestrator cannot import Smith: Smith is the layer above it, and
:mod:`services.smith.gate` already imports :func:`orchestrator.transition`.

The fingerprint
---------------
:func:`product_digest` hashes the application's *product surface* — the
identity and name of every artifact a user would recognise, plus the design
direction. Not prose: a reworded page purpose has not changed the application
someone agreed to, while a page appearing, disappearing or being renamed has.

That distinction is the whole value. §76 says the Blueprint and the
implementation must not silently diverge; an approval with no fingerprint
diverges from what was approved and nothing can tell. With one, an approval
whose digest no longer matches is *stale* rather than quietly current, and
:func:`require` refuses on it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

#: The sections whose membership defines the application a user approved.
#: A change to any of them is a change to what they agreed to; a change
#: anywhere else is not. Listed rather than derived, because that judgement is
#: the contract — adding a section here invalidates existing approvals, and
#: that should be a decision someone makes on purpose.
DIGEST_SECTIONS: tuple[str, ...] = (
    "roles",
    "permissions",
    "modules",
    "pages",
    "workflows",
    "businessRules",
    "integrations",
    "widgets",             # §24 "reports"
    "data.entities",
    "product.capabilities",
    "product.personas",    # §24 "users"
)

ApprovalState = Literal["approved", "stale", "open"]


class NotApproved(RuntimeError):
    """The work about to be done has not been authorised (§95)."""


def _items(doc: dict, path: str) -> list[dict]:
    node: Any = doc
    for part in path.split("."):
        node = (node or {}).get(part) if isinstance(node, dict) else None
    return [
        i for i in (node or [])
        if isinstance(i, dict) and i.get("status") != "DEPRECATED"
    ]


def identity_material(doc: dict) -> dict[str, Any]:
    """Exactly what the fingerprint is taken over. Exposed so it is auditable.

    An opaque hash that nobody can explain is not much better than no hash: if
    a user asks "why did my approval go stale", the answer has to be
    inspectable.
    """
    application = doc.get("application") or {}
    product = doc.get("product") or {}
    design = doc.get("designSystem") or {}

    material: dict[str, Any] = {
        "name": str(application.get("name") or ""),
        "domain": str(application.get("domain") or ""),
        "objectives": sorted(str(o) for o in (product.get("objectives") or [])),
        # Which keys are set, not their prose. A security model gaining an
        # `authorization` policy is a change; rewording its description is not.
        "security": sorted(k for k, v in (doc.get("security") or {}).items() if v),
        "design": {
            "visualPersonality": design.get("visualPersonality") or "",
            "navigationApproach": design.get("navigationApproach") or "",
            "informationDensity": design.get("informationDensity") or "",
            "derivedFromFigma": bool(design.get("derivedFromFigma")),
            "sources": sorted(
                str(s.get("id")) for s in (doc.get("designSources") or [])
                if s.get("id")
            ),
        },
    }
    for path in DIGEST_SECTIONS:
        material[path] = sorted(
            f"{i.get('id') or ''}:{i.get('name') or ''}" for i in _items(doc, path)
        )
    return material


def product_digest(doc: dict) -> str:
    """A short, stable fingerprint of the application's product surface."""
    encoded = json.dumps(
        identity_material(doc), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def requirements_digest(doc: dict) -> str:
    """A fingerprint of what the requirements say.

    The understanding gate is answered against the requirements alone — at
    that gate nothing else exists yet, so the product surface is empty and its
    digest would call every later requirements edit "still approved". Here the
    prose IS the thing agreed to: rewording "24 hours" to "12 hours" changes
    what the application must do.
    """
    material = sorted(
        f"{r.get('id') or ''}:{r.get('description') or ''}"
        for r in _items(doc, "requirements")
    )
    encoded = json.dumps(material, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def digest_for(doc: dict, gate: str) -> str:
    """What an answer at ``gate`` is taken against."""
    return requirements_digest(doc) if gate == "understanding" else product_digest(doc)


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def latest(doc: dict, gate: str) -> dict[str, Any] | None:
    """The most recent answer at ``gate``, whatever it was."""
    answers = [
        a for a in (doc.get("approvals") or []) if a.get("gate") == gate
    ]
    return answers[-1] if answers else None


def state_of(doc: dict, gate: str) -> ApprovalState:
    """``approved`` only when the answer was yes *and* still describes this doc."""
    answer = latest(doc, gate)
    if answer is None or answer.get("outcome") != "accepted":
        return "open"
    return "approved" if answer.get("digest") == digest_for(doc, gate) else "stale"


def is_approved(doc: dict, gate: str) -> bool:
    return state_of(doc, gate) == "approved"


def record(svc: Any, gate: str, outcome: str = "accepted", *,
           message_id: str = "", note: str = "") -> dict[str, Any]:
    """Write one §25 answer, fingerprinted against the document as it stands.

    The fingerprint is taken here rather than passed in: an approval recorded
    against anything but the document being approved is the bug this whole
    module exists to prevent.
    """
    from datetime import datetime, timezone

    entry = {
        "gate": gate,
        "outcome": outcome,
        "version": int(svc.doc.get("version") or 1),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "digest": digest_for(svc.doc, gate),
        "message": message_id,
        "note": note,
    }
    svc.doc.setdefault("approvals", []).append(entry)
    svc.save()
    return entry


def carry(svc: Any, gate: str, *, why: str) -> dict[str, Any] | None:
    """Carry an approval over what the approved work itself wrote.

    A build that was approved fills in the very things the fingerprint is
    taken over — the sign-in pages, the design system, the security rules,
    the workflows a huddle adds — so every build left its own approval stale,
    and "rebuild" was refused with "approved at version 20, now at 68" by a
    tester who had changed nothing (Lifestyle App, forge-v3, 2026-10-09).
    Called by the build at its own checkpoints, only when the approval stood
    when it started: what it wrote is what was agreed to. A change made
    outside a build still makes the approval stale. Returns the new entry,
    or None when there was nothing to carry."""
    if state_of(svc.doc, gate) != "stale":
        return None
    last = latest(svc.doc, gate) or {}
    if last.get("outcome") != "accepted":
        return None
    return record(svc, gate, note=f"carried: {why}")


def require(doc: dict, gate: str, *, doing: str = "") -> None:
    """Raise unless ``gate`` is satisfied against the document as it stands.

    ``doing`` names the work being guarded, so the refusal says what was
    stopped rather than only what was missing.
    """
    state = state_of(doc, gate)
    if state == "approved":
        return

    answer = latest(doc, gate) or {}
    if state == "stale":
        reason = (
            f"the {gate!r} gate was accepted at version "
            f"{answer.get('version', '?')}, but the application has changed "
            f"since and needs to be reviewed again (§76)"
        )
    elif answer.get("outcome") == "changes_requested":
        note = str(answer.get("note") or "").strip()
        reason = (
            f"changes were requested at the {gate!r} gate and have not been "
            f"re-approved" + (f": {note}" if note else "")
        )
    else:
        reason = f"the {gate!r} gate has not been accepted (§95)"

    # The clause goes last, so every reason reads as a sentence rather than
    # having the work spliced into the middle of it.
    raise NotApproved(reason + (f" — cannot proceed with {doing}" if doing else ""))

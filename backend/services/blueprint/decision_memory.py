"""§20 — decision memory, written from the confidence the Blueprint already carries.

§17 makes confidence operational: above 0.90 an agent decides on its own;
between 0.70 and 0.90 it "records an assumption"; between 0.40 and 0.70 it asks;
below that it blocks. The middle band is the one with a side effect — recording
an assumption means *writing it down somewhere* — and nothing wrote it down.
``decisions`` stayed empty through every run, which had a real cost: agents
cited DEC ids that could not exist, so the field had to be withheld from them
entirely.

The fix is not another agent. Every artifact already carries the confidence its
author assigned and the requirements it serves, so the assumptions are derivable
— and §116 says what is derivable belongs to deterministic code. Re-deriving is
idempotent because each decision is keyed by the artifact it concerns.

What this does *not* do is invent rationale. A decision records what was assumed
and how sure the author was; it does not manufacture a justification nobody
gave. Where an artifact carries a ``syncNote`` — the author's own words about
why — that is used verbatim.
"""
from __future__ import annotations

from typing import Any

from services.blueprint.agent_contract import ASK_USER, AUTO_DECIDE, RECORD_ASSUMPTION

#: Sections whose artifacts are design choices worth remembering. Requirements
#: and tests are excluded: a requirement is an input, not a decision, and a test
#: is a consequence of one.
DECIDABLE_SECTIONS: tuple[str, ...] = (
    "modules", "pages", "components", "widgets", "workflows",
    "businessRules", "apis", "integrations", "patternTemplates",
)


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _label(section: str, artifact: dict) -> str:
    return (artifact.get("name") or artifact.get("label") or artifact.get("pattern")
            or artifact.get("path") or artifact.get("id") or section)


def assumptions(doc: dict) -> list[dict]:
    """Every artifact whose confidence puts it in §17's record-an-assumption band.

    Emitted in a stable order so two derivations over the same Blueprint produce
    the same list.
    """
    out: list[dict] = []
    for section in DECIDABLE_SECTIONS:
        for artifact in _live(doc.get(section)):
            confidence = artifact.get("confidence")
            if confidence is None or not (RECORD_ASSUMPTION <= confidence < AUTO_DECIDE):
                continue
            artifact_id = artifact.get("id") or artifact.get("pattern")
            if not artifact_id:
                continue
            reason = artifact.get("syncNote") or (
                f"Assumed while designing {section}; confidence {confidence:.2f} "
                f"sits in §17's record-an-assumption band (>= "
                f"{RECORD_ASSUMPTION:.2f} and < {AUTO_DECIDE:.2f})."
            )
            out.append({
                # §20's `source` is a closed set. An assumption an agent made
                # from what the domain usually implies is `domain_default` —
                # the honest option. It is explicitly *not* `user`, which would
                # claim someone approved it.
                "decision": f"{_label(section, artifact)} ({artifact_id}) "
                            f"as specified in {section}",
                "reason": reason,
                "source": "domain_default",
                "binding": True,
                "_artifact": artifact_id,
            })
    return out


def unresolved_questions(doc: dict) -> list[dict]:
    """Artifacts below §17's ask-the-user line — recorded, never silently kept.

    These are not decisions; they are the absence of one. Surfacing them beside
    the decisions is what stops a low-confidence guess from reading like a
    settled choice.
    """
    out: list[dict] = []
    for section in DECIDABLE_SECTIONS:
        for artifact in _live(doc.get(section)):
            confidence = artifact.get("confidence")
            if confidence is None or confidence >= RECORD_ASSUMPTION:
                continue
            out.append({
                "artifact": artifact.get("id") or artifact.get("pattern"),
                "section": section,
                "confidence": confidence,
                "needs": "clarification" if confidence >= ASK_USER else "blocked",
                "label": _label(section, artifact),
            })
    return out


def user_decided(svc: Any) -> set[str]:
    """Artifacts whose decision the user made themselves (§20).

    The link from a decision back to its artifact is the ID allocator's
    binding, not a field on the decision: ``decisions`` is a closed schema with
    nowhere to record the subject, and the natural key a decision was upserted
    under *is* the artifact id. So the registry answers this exactly, which is
    what an identity registry is for.
    """
    from services.blueprint.ids import IdAllocator

    by_id = {d.get("id"): d for d in (svc.doc.get("decisions") or [])}
    alloc = IdAllocator.load(output_dir=svc.output_dir)
    owned: set[str] = set()
    for natural_key, artifact_id in alloc.bindings.items():
        if not artifact_id.startswith("DEC-"):
            continue
        decision = by_id.get(artifact_id)
        if not decision:
            continue
        if decision.get("source") == "user" or decision.get("approvedBy") == "user":
            owned.add(natural_key)
    return owned


def apply_decision_memory(svc: Any) -> dict[str, int]:
    """Derive and upsert. Keyed on the artifact, so re-running is a no-op.

    A derivation never overwrites a decision the user made. Both records are
    keyed on the same artifact, so without this the next run would replace
    ``source: user`` with ``source: domain_default`` and the Blueprint would
    quietly stop remembering that anyone was asked. §20's whole point is that
    "future agents must respect accepted decisions unless deliberately
    changed", and a re-derivation is not a deliberate change.

    In practice ``assumptions`` rarely reaches these anyway — recording a user
    decision lifts the artifact's confidence out of the record-an-assumption
    band. That is a side effect of another module, though, and this invariant
    is too load-bearing to rest on one.
    """
    protected = user_decided(svc)
    recorded = assumptions(svc.doc)
    written = 0
    for decision in recorded:
        artifact_id = decision["_artifact"]
        if artifact_id in protected:
            continue
        body = {k: v for k, v in decision.items() if k != "_artifact"}
        body["version"] = svc.doc.get("version", 1)
        svc.upsert("decisions", body, natural_key=artifact_id)
        written += 1
    svc.save()
    return {
        "recorded": written,
        "preserved": len(protected),
        "unresolved": len(unresolved_questions(svc.doc)),
    }

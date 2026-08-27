"""§20 — recording the decisions the user actually made.

``decision_memory`` derives decisions from confidence: an artifact an agent was
75% sure about becomes a ``domain_default`` assumption on the record. That is
the right treatment for a guess, and the wrong treatment for an answer. §20's
own example is not a guess::

    decision:
      id: DEC-008
      decision: Use left navigation.
      reason:   Application contains multiple operational modules.
      source:   Smith recommendation.
      approvedBy: user

and it closes with the sentence that makes this module load-bearing: *"Future
agents must respect accepted decisions unless deliberately changed."*

Answering a question is a Blueprint write
-----------------------------------------
The interesting part is what happens to the artifact, not to the decision.

§17's bands are not a confidence report — they are an authority grant. Above
0.90 an agent may decide alone; below 0.40 it may not implement the behaviour
at all. So when the user answers, the thing that changes is how much authority
the platform has over that artifact, and that is exactly what ``confidence``
means. Recording the answer raises it, and the artifact stops appearing in
``clarification.candidates`` — not because anything crossed it off a list, but
because it is no longer true that nobody knows.

That is why there is no question queue anywhere in this package. An open
question is a derived property of the Blueprint. A stored one would be a second
source of truth that has to be kept in step with the first, and §115 admits
exactly one.

Two kinds of answer
-------------------
``"reject after offer requires a reason"``  — the user decided. Confidence 1.0,
``source: user``.

``"you decide"`` — the user delegated. Confidence lands on ``AUTO_DECIDE``
(0.90) and ``source: smith_recommendation``. Not 1.0, because nobody became
certain; 0.90 because that is precisely the band where §17 says Smith may
decide alone, and granting that band is what delegation *is*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.blueprint.agent_contract import AUTO_DECIDE
from services.blueprint.service import ArtifactNotFound, BlueprintService

#: §20's closed source set, mirrored from the contract.
SOURCES: tuple[str, ...] = ("user", "smith_recommendation", "domain_default", "figma")

#: Where an answered artifact's confidence lands. See the module docstring —
#: these are authority grants, not beliefs.
ANSWERED_CONFIDENCE = 1.0
DELEGATED_CONFIDENCE = AUTO_DECIDE


class NotADecision(ValueError):
    """The decision is empty, or names an artifact that does not exist."""


@dataclass(frozen=True)
class RecordedDecision:
    """What was written, so the caller can report it without re-reading."""

    id: str
    artifact: str
    decision: str
    source: str
    confidence: float
    message: str = ""

    @property
    def delegated(self) -> bool:
        return self.source == "smith_recommendation"


def _add_evidence(artifact: dict, message_id: str) -> None:
    """Cite the message that settled this, per §14.

    Only ``requirements`` declares an ``evidence`` array in the contract, so
    this is a no-op elsewhere rather than a schema violation. Widening the
    schema to let every artifact carry evidence is a defensible change and a
    separate one; silently attaching a field the contract rejects is not.
    """
    if not message_id or "evidence" not in artifact and "description" not in artifact:
        return
    evidence = artifact.get("evidence")
    if not isinstance(evidence, list):
        return
    entry = {"type": "conversation", "message": message_id, "source": "user"}
    if entry not in evidence:
        evidence.append(entry)


def record(
    svc: BlueprintService,
    *,
    artifact_id: str,
    decision: str,
    reason: str = "",
    message_id: str = "",
    delegated: bool = False,
) -> RecordedDecision:
    """Write one user decision and settle the artifact it concerns.

    Raises rather than tolerating an unknown artifact. A decision floating free
    of the thing it decides cannot be honoured by a future agent, cannot be
    superseded, and cannot be found again — it is a note, not a decision.
    """
    text = (decision or "").strip()
    if not text:
        raise NotADecision("a decision needs a statement of what was decided")

    try:
        _section, artifact = svc.find(artifact_id)
    except (ArtifactNotFound, KeyError) as exc:
        raise NotADecision(
            f"{artifact_id!r} is not an artifact in this Blueprint; a decision "
            "must name what it decides"
        ) from exc

    source = "smith_recommendation" if delegated else "user"
    confidence = DELEGATED_CONFIDENCE if delegated else ANSWERED_CONFIDENCE

    body = {
        "decision": text,
        "reason": (reason or "").strip(),
        "source": source,
        # approvedBy is `user` either way. Delegation is still approval — the
        # user was asked and answered "you choose", which binds them to the
        # outcome in a way a domain default never does.
        "approvedBy": "user",
        "binding": True,
        "status": "APPROVED",
        "version": svc.doc.get("version", 1),
    }

    # Supersede rather than overwrite (§20, §92): a decision that replaces an
    # earlier one about the same artifact should say so, so the history reads
    # as a change of mind instead of as if the first was never made.
    previous = _existing_for(svc, artifact_id)
    if previous and previous.get("decision") != text:
        body["supersedes"] = previous["id"]

    written = svc.upsert("decisions", body, natural_key=artifact_id)

    artifact["confidence"] = confidence
    _add_evidence(artifact, message_id)
    svc.validate()
    svc.save()

    return RecordedDecision(
        id=written["id"],
        artifact=artifact_id,
        decision=text,
        source=source,
        confidence=confidence,
        message=message_id,
    )


def _existing_for(svc: BlueprintService, artifact_id: str) -> dict | None:
    """The decision already recorded about this artifact, if any.

    Found through the ID allocator's binding, because ``decisions`` is a closed
    schema with no field naming its subject and the natural key it was upserted
    under is the artifact id.
    """
    from services.blueprint.ids import IdAllocator

    alloc = IdAllocator.load(output_dir=svc.output_dir)
    decision_id = alloc.lookup(artifact_id)
    if not decision_id or not decision_id.startswith("DEC-"):
        return None
    for d in svc.doc.get("decisions") or []:
        if d.get("id") == decision_id:
            return d
    return None


def by_user(doc: dict) -> list[dict]:
    """Decisions the user made or approved — §20's "accepted decisions".

    What a future agent must respect. Sorted by id so two reads agree.
    """
    return sorted(
        (
            d for d in (doc.get("decisions") or [])
            if d.get("source") == "user" or d.get("approvedBy") == "user"
        ),
        key=lambda d: d.get("id", ""),
    )


def binding_for(doc: dict, artifact_ids: Any) -> list[dict]:
    """User decisions relevant to a set of artifacts, for a prompt.

    Note this cannot filter precisely without the allocator, so it returns
    every binding user decision when the caller has no output_dir to resolve
    against. Over-including a decision costs tokens; under-including one lets
    an agent contradict something the user settled, which §20 forbids outright.
    """
    wanted = set(artifact_ids or ())
    decisions = by_user(doc)
    if not wanted:
        return decisions
    return decisions

"""§16 — deciding which three-to-five questions are worth the user's attention.

§16 sets a budget, not a policy: *"Smith should not interrogate the user with
dozens of questions. Questions should be grouped into approximately 3–5
important decisions at a time."* §15 supplies the missing half — ask *"when
missing information materially affects the application."*

On the ATS fixture there are 57 artifacts sitting below §17's ask-the-user
line. Five of them get asked. So the whole module is really one function:
which five, and why those.

Selection is deterministic (§116). Materiality is not a matter of taste — it is
three things the Blueprint already knows:

* **How unsure the author was.** Below 0.40 §17 says do not implement the
  behaviour at all; that outranks merely wanting confirmation.
* **How much depends on it.** An artifact twelve others reference is a worse
  thing to guess about than one nothing references. This is §19's graph read as
  in-degree.
* **Whether its whole dimension is thin.** §23 already scores this. A page in
  an application with no workflows modelled is a different question from a page
  in a well-modelled one.

Only the *wording* is left to the model, and that is genuine §116 generation:
turning ``FLOW-004 confidence 0.55`` into "Can a recruiter reject a candidate
after an offer has gone out?" is interpretation, and nothing else here is.

Why the scope is wider than ``decision_memory.unresolved_questions``
--------------------------------------------------------------------
That function scopes to ``DECIDABLE_SECTIONS``, which excludes requirements —
correctly, for its purpose, because §20 records *decisions* and a requirement is
an input rather than a decision.

For questions the exclusion is backwards. On the ATS fixture **nine of eighteen
requirements** sit below the ask line, and a requirement Smith is 55% sure it
understood is the single most material thing in the document to get wrong:
everything downstream inherits the misunderstanding. So questions are gathered
from a wider set, and ``unresolved_questions`` is left alone to mean what it
means.

``apis`` are excluded in the other direction. They are derived by
``api_derivation`` from entities, workflows and widgets — a low-confidence
endpoint is a symptom, and asking the user to confirm it is asking about the
shadow instead of the thing casting it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.blueprint.agent_contract import ASK_USER, RECORD_ASSUMPTION
from services.blueprint.completeness import score as completeness_score
from services.blueprint.orchestrator import graph_pool, refs_of

#: Sections a user can meaningfully be asked about. See the module docstring
#: for why this differs from ``decision_memory.DECIDABLE_SECTIONS`` in both
#: directions.
QUESTION_SECTIONS: tuple[str, ...] = (
    "requirements", "data.entities", "modules", "pages", "components",
    "widgets", "workflows", "businessRules", "integrations", "roles",
    "permissions",
)

#: Which §23 dimension each section's health is measured by, so "this whole
#: area is thin" can weigh on the question.
SECTION_DIMENSION: dict[str, str] = {
    "requirements": "capabilities",
    "data.entities": "data",
    "modules": "capabilities",
    "pages": "pages",
    "components": "pages",
    "widgets": "reporting",
    "workflows": "workflows",
    "businessRules": "businessRules",
    "integrations": "integrations",
    "roles": "roles",
    "permissions": "security",
}

#: Relative weights. Stated as constants rather than buried in the expression
#: because they are the arguable part — the ranking is only as good as these,
#: and someone should be able to disagree with a number rather than with code.
W_BLOCKED = 2.0      # §17: below 0.40, do not implement without clarification
W_DEFICIT = 1.5      # how far below the ask line
W_BLAST = 2.0        # §19 in-degree — how much rides on the answer
W_DIMENSION = 1.0    # §23 — is the whole dimension thin

#: §16's "approximately 3–5".
DEFAULT_BATCH = 5

#: How many recent Smith turns count as "already asked". Small: a user who
#: ignored a question twice and kept talking has answered it by conduct.
ASK_MEMORY = 3


@dataclass(frozen=True)
class Question:
    """One thing worth asking, with the arithmetic that chose it."""

    artifact: str
    section: str
    label: str
    confidence: float
    #: ``blocked`` below §17's 0.40, ``clarification`` between 0.40 and 0.70.
    needs: str
    #: How many artifacts reference this one.
    blast: int
    score: float
    why: str

    @property
    def blocking(self) -> bool:
        return self.needs == "blocked"


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _label(artifact: dict, section: str) -> str:
    return (artifact.get("name") or artifact.get("label") or artifact.get("title")
            or artifact.get("description") or artifact.get("route")
            or artifact.get("id") or section)


def in_degree(doc: dict) -> dict[str, int]:
    """How many artifacts reference each artifact — §19's graph as a count.

    Direct references only, not the transitive closure. Transitively almost
    everything reaches almost everything (module membership alone connects
    every page to every other), so a transitive count ranks nothing above
    anything else.
    """
    counts: dict[str, int] = {}
    for _section, art in graph_pool(doc):
        for ref in refs_of(art):
            counts[ref] = counts.get(ref, 0) + 1
    return counts


def candidates(doc: dict) -> list[Question]:
    """Every artifact below §17's ask-the-user line, scored for materiality."""
    degree = in_degree(doc)
    max_degree = max(degree.values(), default=1) or 1
    dimensions = completeness_score(doc)

    out: list[Question] = []
    for section in QUESTION_SECTIONS:
        if section == "data.entities":
            items = _live((doc.get("data") or {}).get("entities"))
        else:
            items = _live(doc.get(section))
        for art in items:
            confidence = art.get("confidence")
            artifact_id = art.get("id")
            if confidence is None or artifact_id is None:
                continue
            if confidence >= RECORD_ASSUMPTION:
                continue

            blocked = confidence < ASK_USER
            deficit = (RECORD_ASSUMPTION - confidence) / RECORD_ASSUMPTION
            blast = degree.get(artifact_id, 0)
            dimension = SECTION_DIMENSION.get(section, "")
            thinness = 1.0 - dimensions.get(dimension, 1.0)

            score = (
                (W_BLOCKED if blocked else 0.0)
                + W_DEFICIT * deficit
                + W_BLAST * (blast / max_degree)
                + W_DIMENSION * thinness
            )

            reasons = []
            if blocked:
                reasons.append(f"below §17's {ASK_USER:.2f} line — must not be implemented on a guess")
            else:
                reasons.append(f"confidence {confidence:.2f}")
            if blast:
                reasons.append(f"{blast} artifact(s) depend on it")
            if thinness > 0.3:
                reasons.append(f"{dimension} is only {dimensions.get(dimension, 0):.0%} evidenced")

            out.append(Question(
                artifact=artifact_id,
                section=section,
                label=str(_label(art, section))[:160],
                confidence=float(confidence),
                needs="blocked" if blocked else "clarification",
                blast=blast,
                score=round(score, 4),
                why="; ".join(reasons),
            ))

    out.sort(key=lambda q: (-q.score, q.artifact))
    return out


def already_asked(conversation: Any, *, turns: int = ASK_MEMORY) -> set[str]:
    """Artifacts Smith asked about in its last few turns.

    Derived from the transcript rather than stored as a queue. A question is
    not a thing with a lifecycle — it is the observation that an artifact is
    under-confident, and it stops being true when the artifact stops being
    under-confident. Keeping a separate list of open questions would create a
    second source of truth that has to be reconciled with the first, which is
    the shape of bug this architecture exists to avoid.
    """
    if conversation is None:
        return set()
    asked: set[str] = set()
    smith_turns = [m for m in conversation.messages() if m.role == "smith"]
    for message in smith_turns[-turns:] if turns > 0 else []:
        asked.update(message.refs)
    return asked


def select(
    doc: dict,
    *,
    conversation: Any = None,
    limit: int = DEFAULT_BATCH,
    diversify: bool = True,
) -> list[Question]:
    """§16's batch — the most material 3–5, spread across sections.

    ``diversify`` round-robins across sections so a batch is not five widgets.
    The reason is not variety for its own sake: five questions about one
    section are five ways of asking the same underlying question, and the user
    answers the first one and is bored by the fifth. One question per section
    gets four different pieces of information for the same attention.

    The highest-scoring question is always first regardless, so the single most
    material thing is never displaced by the wish to spread out.
    """
    pool = [q for q in candidates(doc) if q.artifact not in already_asked(conversation)]
    if not pool or limit <= 0:
        return []
    if not diversify:
        return pool[:limit]

    by_section: dict[str, list[Question]] = {}
    for q in pool:
        by_section.setdefault(q.section, []).append(q)

    # Sections in order of their best question, so round-robin starts with the
    # most material section rather than alphabetically.
    order = sorted(by_section, key=lambda s: -by_section[s][0].score)

    chosen: list[Question] = []
    rank = 0
    while len(chosen) < limit:
        added = False
        for section in order:
            bucket = by_section[section]
            if rank < len(bucket):
                chosen.append(bucket[rank])
                added = True
                if len(chosen) == limit:
                    break
        if not added:
            break
        rank += 1
    return chosen


def summary(doc: dict) -> dict[str, Any]:
    """What is open, for a status line — counts, not the questions themselves."""
    pool = candidates(doc)
    return {
        "open": len(pool),
        "blocking": sum(1 for q in pool if q.blocking),
        "sections": sorted({q.section for q in pool}),
        # Only dimensions that are actually thin. Reporting the bottom three
        # unconditionally names three "weakest" dimensions even when all eleven
        # score 1.0 — which is what the ATS fixture does, and it reads as a
        # finding when it is an artefact of sorting equal values.
        "weakest": [
            d for d, v in sorted(completeness_score(doc).items(), key=lambda kv: kv[1])
            if v < 1.0
        ][:3],
    }

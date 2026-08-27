"""The Context Resolver (PRD §8) — retrieve only what the request is about.

§8 draws it as the thing standing between Smith and its three stores::

                          SMITH
                            │
                     Context Resolver
                            │
            ┌───────────┼─────────────┐
          ↓             ↓             ↓
    Conversation     Blueprint     Code Index
            └───────────┼─────────────┘
                            ↓
                     Relevant Context

and then states the requirement plainly: *"Smith should retrieve only context
relevant to the current request."*

This is deterministic, and that is a §116 call rather than a shortcut. Ranking
artifacts by how well they match a request is derivable — it is string matching
over fields the Blueprint already carries, followed by a walk over §19's graph.
A model asked to pick relevant artifacts would do the same job less
reproducibly, and would cost a round-trip *before* the round-trip that does the
actual work.

Three ways in, in descending order of certainty:

**Anchors.** §69's preview selection already says which page and which
component. Nothing needs inferring; the UI knew.

**Explicit ids.** A request naming ``PAGE-014`` means PAGE-014.

**Lexical match.** Otherwise, score artifacts against the request's words over
their identity fields — a name, a route, an entity. This is the weakest signal
and it is treated as such: it seeds a graph walk rather than deciding anything,
and where it comes up empty the resolver says so instead of guessing.

The budget matters as much as the ranking. The ATS fixture is ~313 artifacts
and roughly 80k tokens of JSON; handing all of it to every turn is what makes a
conversation cost more than the work. The slice is capped and the cap is
reported, so a truncated context is visible rather than assumed complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.blueprint.ids import is_valid_id, parse_id
from services.blueprint.orchestrator import graph_pool
from services.smith.code_intel import dependencies, where

#: Fields that carry an artifact's identity — what a user would call it by.
#: Weighted above prose, because "candidate table" should find the component
#: named CandidateTable rather than every description mentioning candidates.
IDENTITY_FIELDS: tuple[str, ...] = (
    "name", "label", "title", "route", "path", "pattern", "table", "action",
)
PROSE_FIELDS: tuple[str, ...] = ("description", "purpose", "summary", "expression")

IDENTITY_WEIGHT = 3
PROSE_WEIGHT = 1

#: Words that match everything and therefore distinguish nothing. Kept short on
#: purpose — an aggressive stop list starts eating domain terms, and in an ATS
#: "offer" and "role" are content words even though they look generic.
STOPWORDS: frozenset[str] = frozenset("""
a an and are as at be by can could do does for from has have how i if in into
is it its make me more my need of on or please should show that the their then
there these this to up us use want was we what when where which who why will
with would you your
""".split())

ID_MENTION = re.compile(r"\b(?:REQ|ROLE|PERM|MODULE|PAGE|CMP|ENTITY|FLOW|RULE|API|TEST|DEC|INT|DEP|WIDGET)-\d{3,}\b")

#: Sections carried through into a resolved slice as whole objects — they are
#: small, and every request needs them to make sense of the rest.
ALWAYS: tuple[str, ...] = (
    "schemaVersion", "version", "state", "application", "product",
    "navigation", "designSystem", "completeness",
)

#: Default artifact budget for one slice.
DEFAULT_BUDGET = 60


#: Split PascalCase and camelCase before lowercasing. Without this,
#: ``CandidateTable`` becomes the single token ``candidatetable`` and the
#: request "make the candidate table more compact" matches every API mentioning
#: candidates while missing the component the user is actually pointing at.
_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokens(text: str) -> set[str]:
    split = _CASE_BOUNDARY.sub(" ", text or "")
    return {
        w for w in re.split(r"[^a-z0-9]+", split.lower())
        if len(w) > 2 and w not in STOPWORDS
    }


def _identity_text(art: dict) -> str:
    parts = [str(art.get(f, "")) for f in IDENTITY_FIELDS]
    if isinstance(art.get("method"), str):
        parts.append(art["method"])
    return " ".join(p for p in parts if p)


@dataclass
class Scored:
    artifact_id: str
    section: str
    score: float
    why: str


@dataclass
class Context:
    """What Smith is allowed to think with on this turn."""

    request: str
    #: The Blueprint, sliced to relevant artifacts. Same section keys as the
    #: full document, so it serialises into a prompt unchanged.
    blueprint: dict = field(default_factory=dict)
    #: Artifact ids in the slice, best match first.
    artifacts: list[str] = field(default_factory=list)
    #: How each seed was found — anchor, explicit id, or which words matched.
    why: dict[str, str] = field(default_factory=dict)
    #: Layer 1: the immediate exchange, as ``{id, role, text}``.
    conversation: list[dict] = field(default_factory=list)
    #: Layer 3: decisions binding on the artifacts in this slice.
    decisions: list[dict] = field(default_factory=list)
    #: Layer 4: files implementing them.
    code: dict[str, list[str]] = field(default_factory=dict)
    #: True when the budget cut the slice — the caller is not looking at
    #: everything that matched, and should not claim otherwise.
    truncated: bool = False
    #: Nothing matched. Distinct from an empty application: it means the
    #: request did not name anything this Blueprint knows about, which is a
    #: reason to ask rather than to answer.
    grounded: bool = True

    def artifact_count(self) -> int:
        return len(self.artifacts)


def score_artifacts(doc: dict, request: str) -> list[Scored]:
    """Rank every artifact by lexical match against the request.

    Returns only artifacts that matched at all — a zero score is not a weak
    signal, it is the absence of one, and carrying zeros forward would let the
    budget fill with noise ranked by artifact id.
    """
    wanted = _tokens(request)
    if not wanted:
        return []
    out: list[Scored] = []
    for section, art in graph_pool(doc):
        artifact_id = art.get("id")
        if not artifact_id or art.get("status") == "DEPRECATED":
            continue
        ident = _tokens(_identity_text(art))
        prose = _tokens(" ".join(str(art.get(f, "")) for f in PROSE_FIELDS))
        hit_ident = wanted & ident
        hit_prose = (wanted & prose) - hit_ident
        if not hit_ident and not hit_prose:
            continue
        score = IDENTITY_WEIGHT * len(hit_ident) + PROSE_WEIGHT * len(hit_prose)
        matched = ", ".join(sorted(hit_ident | hit_prose))
        out.append(Scored(artifact_id, section, float(score), f"matched: {matched}"))
    out.sort(key=lambda s: (-s.score, parse_id(s.artifact_id)))
    return out


def _slice(doc: dict, keep: set[str]) -> dict:
    """The Blueprint restricted to ``keep``, with section keys intact."""
    out: dict[str, Any] = {k: doc[k] for k in ALWAYS if k in doc}
    for section, art in graph_pool(doc):
        if section == "codeMap" or art.get("id") not in keep:
            continue
        if section == "data.entities":
            out.setdefault("data", {}).setdefault("entities", []).append(art)
        else:
            out.setdefault(section, []).append(art)
    # Relationships and constraints follow their entities: an entity shown
    # without its foreign keys reads as though it has none.
    entity_ids = {e["id"] for e in out.get("data", {}).get("entities", [])}
    if entity_ids:
        data = doc.get("data") or {}
        for child in ("relationships", "constraints"):
            rows = [
                r for r in (data.get(child) or [])
                if {r.get("from"), r.get("to"), r.get("entity")} & entity_ids
            ]
            if rows:
                out.setdefault("data", {})[child] = rows
    return out


def resolve(
    doc: dict,
    request: str,
    *,
    anchors: list[str] | tuple[str, ...] = (),
    conversation: Any = None,
    budget: int = DEFAULT_BUDGET,
    expand: bool = True,
) -> Context:
    """Assemble the slice for one request.

    ``anchors`` are artifacts the caller already knows the request is about —
    a §69 preview selection, or the artifacts a clarification batch asked
    about. They bypass matching entirely and are never dropped by the budget:
    a resolver that budgets away the component the user literally clicked has
    failed at the one case where it had certainty.
    """
    known = {
        art["id"] for _s, art in graph_pool(doc) if art.get("id")
    }

    why: dict[str, str] = {}
    seeds: list[str] = []

    for anchor in anchors:
        if anchor in known and anchor not in why:
            why[anchor] = "anchor: named by the caller"
            seeds.append(anchor)

    for mention in ID_MENTION.findall(request or ""):
        if mention in known and mention not in why:
            why[mention] = "named in the request"
            seeds.append(mention)

    ranked = score_artifacts(doc, request)
    for hit in ranked:
        if hit.artifact_id not in why:
            why[hit.artifact_id] = hit.why
            seeds.append(hit.artifact_id)

    grounded = bool(seeds)

    # Anchors and explicit mentions are guaranteed; matched artifacts fill the
    # remaining budget in rank order.
    guaranteed = [s for s in seeds if why[s].startswith(("anchor", "named"))]
    optional = [s for s in seeds if s not in guaranteed]
    room = max(0, budget - len(guaranteed))
    kept = guaranteed + optional[:room]
    truncated = len(optional) > room

    keep = set(kept)
    if expand:
        # One hop, so a page arrives with its entity and its module and stops
        # there. Expansion is not budgeted against the seeds — dropping an
        # entity a kept page depends on would produce a slice that contradicts
        # itself — which is exactly why it must be bounded instead. The full
        # closure reaches a role, and a role reaches every permission; on the
        # ATS fixture that turned a 60-artifact slice into 152.
        keep |= {a for a in dependencies(doc, set(kept), depth=1) if a in known}

    ordered = kept + sorted(keep - set(kept), key=lambda i: parse_id(i))

    decisions = [
        d for d in (doc.get("decisions") or [])
        if d.get("binding", True)
    ]

    code = {}
    for artifact_id in ordered:
        loc = where(doc, artifact_id)
        if loc.mapped:
            code[artifact_id] = list(loc.files)

    recent: list[dict] = []
    if conversation is not None:
        recent = [
            {"id": m.id, "role": m.role, "text": m.text}
            for m in conversation.recent(10)
        ]

    return Context(
        request=request,
        blueprint=_slice(doc, keep),
        artifacts=ordered,
        why=why,
        conversation=recent,
        decisions=decisions,
        code=code,
        truncated=truncated,
        grounded=grounded,
    )

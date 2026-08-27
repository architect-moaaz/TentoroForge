"""Layer 4 — where Blueprint concepts live in the generated code (PRD §8, §18, §21).

§8's fourth memory layer is *"knowledge of where Blueprint concepts exist in the
generated implementation"*, and §21 gives it a home: ``codeMap`` maps an
artifact to the files that implement it. §18 then asks the question the layer
exists to answer::

    Has this requirement been implemented?

Everything here is derived from the Blueprint. Nothing reads the filesystem and
nothing calls a model, because both would answer a different question than the
one asked. Scanning disk tells you what code exists; §115 asks whether the code
matches the *definition*, and only the Blueprint holds that. Where the two
disagree the answer is §76 — flag it — which ``verification.py`` already does.

The trace walks §19's Application Knowledge Graph in both directions, using the
same edge function impact analysis uses::

    reverse   REQ-034 → the pages, workflows and tests that cite it
    forward   those    → the entities and endpoints they depend on

§18's example chain is exactly one path through that::

    REQ-034 → FLOW-009 → RULE-017 → PAGE-014 → API-027 → ENTITY-008 → TEST-088
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.blueprint.ids import is_valid_id, parse_id
from services.blueprint.orchestrator import graph_pool, refs_of

#: §21's implementation facets, in the order a reader wants them.
FACETS: tuple[str, ...] = ("frontend", "api", "service", "test")

#: How §18 groups a trace. Ordered as the PRD's chain reads, so a rendered
#: trace and the PRD's example line up.
CHAIN: tuple[str, ...] = (
    "REQ", "FLOW", "RULE", "MODULE", "PAGE", "CMP", "WIDGET",
    "API", "ENTITY", "PERM", "ROLE", "INT", "TEST",
)


@dataclass(frozen=True)
class CodeLocation:
    """Where one artifact is implemented (§21)."""

    artifact: str
    entity: str | None = None
    frontend: tuple[str, ...] = ()
    api: tuple[str, ...] = ()
    service: tuple[str, ...] = ()
    test: tuple[str, ...] = ()

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.frontend + self.api + self.service + self.test))

    @property
    def mapped(self) -> bool:
        """False means nobody has recorded an implementation for this artifact.

        Distinct from "not implemented": ``codeMap`` is written by the
        projections, so an unmapped artifact is one no projection has run for
        yet. Reporting that as a failure would blame the artifact for the
        pipeline's position.
        """
        return bool(self.files)


@dataclass(frozen=True)
class Trace:
    """§18 — one requirement's reach through the application."""

    requirement: str
    #: prefix -> artifact ids, e.g. {"PAGE": ["PAGE-014"], "API": ["API-027"]}
    chain: dict[str, list[str]] = field(default_factory=dict)
    files: tuple[str, ...] = ()
    verdict: str = "UNKNOWN"
    facets: dict[str, Any] = field(default_factory=dict)

    @property
    def artifacts(self) -> list[str]:
        return [a for prefix in CHAIN for a in self.chain.get(prefix, [])]

    def render(self) -> str:
        """§18's arrow chain, for a human reading an explanation."""
        rungs = [
            f"{prefix}: {', '.join(self.chain[prefix])}"
            for prefix in CHAIN if self.chain.get(prefix)
        ]
        return "\n  ↓\n".join(rungs)


def _index(doc: dict) -> dict[str, dict]:
    """artifact id -> codeMap entry."""
    return {
        e["artifact"]: e
        for e in (doc.get("codeMap") or [])
        if isinstance(e, dict) and e.get("artifact")
    }


def where(doc: dict, artifact_id: str) -> CodeLocation:
    """§21 — the files implementing one artifact."""
    entry = _index(doc).get(artifact_id) or {}
    return CodeLocation(
        artifact=artifact_id,
        entity=entry.get("entity"),
        **{f: tuple(entry.get(f) or ()) for f in FACETS},
    )


def implements(doc: dict, path: str) -> list[str]:
    """Reverse of :func:`where` — which artifacts a source file implements.

    This is what makes a change that starts at a *file* addressable: the user
    edits ``src/app/candidates/page.tsx`` and §115 requires the change to land
    in the Blueprint first, which needs to know what that file is.

    Matches on suffix as well as equality, because a path may be recorded
    relative to the package root and quoted relative to the repository.
    """
    needle = (path or "").strip().lstrip("./")
    if not needle:
        return []
    hits: list[str] = []
    for artifact_id, entry in _index(doc).items():
        for facet in FACETS:
            for recorded in entry.get(facet) or []:
                clean = (recorded or "").lstrip("./")
                if clean == needle or clean.endswith("/" + needle) or needle.endswith("/" + clean):
                    hits.append(artifact_id)
                    break
            else:
                continue
            break
    return sorted(hits)


def dependencies(doc: dict, seeds: set[str], *, depth: int | None = None) -> set[str]:
    """Forward closure — what the seeds reference, and what those reference.

    ``depth`` bounds the walk. Unbounded is right for a trace, which wants the
    whole dependency tail; one hop is right for a conversation slice, where the
    tail is mostly transitive noise — a page pulls in its module, the module
    pulls in a role, and the role pulls in all thirty-seven permissions.

    The complement of :func:`orchestrator.impacted_artifacts`, which closes
    over the *reverse* edges. Keeping the two directions separate is not
    fussiness: closing over both at once reaches the entire application from
    any starting point. A requirement finds its page, the page finds its
    entity, the entity finds every other requirement that touches it, and the
    "trace" is the whole Blueprint — which answers nothing.
    """
    reached = set(seeds)
    by_id = {
        (art.get("id") or art.get("artifact")): art
        for _section, art in graph_pool(doc)
        if art.get("id") or art.get("artifact")
    }
    frontier = set(seeds)
    hops = 0
    while frontier and (depth is None or hops < depth):
        hops += 1
        nxt: set[str] = set()
        for artifact_id in frontier:
            art = by_id.get(artifact_id)
            if not art:
                continue
            for ref in refs_of(art):
                if is_valid_id(ref) and ref not in reached:
                    nxt.add(ref)
        reached |= nxt
        frontier = nxt
    return reached


def serves(doc: dict, requirement_id: str) -> set[str]:
    """Artifacts that declare they serve this requirement — §18's actual link.

    Traceability is carried by the ``requirements`` field an artifact writes
    about itself, not by proximity in the graph. That distinction is the whole
    exercise: a transitive reverse closure from a requirement reaches the entire
    application within three hops, because pages belong to modules and modules
    contain every other page. Measured on the ATS fixture, the closure returns
    249 of ~313 artifacts for *any* requirement — an answer that is the same for
    all eighteen and therefore says nothing. Direct citation returns 19 and 30.

    Impact analysis (§71) is right to close transitively — it is asking what
    might break, and over-reaching there costs regeneration. Traceability is
    asking what this requirement *is*, and over-reaching there is just wrong.
    """
    return {
        art_id
        for _section, art in graph_pool(doc)
        if (art_id := art.get("id")) and requirement_id in (art.get("requirements") or [])
    }


def neighbourhood(doc: dict, requirement_id: str) -> set[str]:
    """§18's reach: what serves the requirement, plus what that work depends on.

    Forward expansion deliberately stops at other requirements. A page serving
    REQ-017 usually serves REQ-004 too; following that edge would drag REQ-004's
    whole trace in and the two would become indistinguishable.
    """
    direct = serves(doc, requirement_id)
    forward = dependencies(doc, direct)
    return {requirement_id} | direct | {
        a for a in forward if not a.startswith("REQ-")
    }


def trace(doc: dict, requirement_id: str) -> Trace:
    """§18 — what implements this requirement, and does it hold up.

    The verdict comes from :func:`verification.requirement_verdict` rather than
    from anything counted here. Two modules answering "is this implemented"
    with two methods is how a report goes green for the wrong reason.
    """
    from services.blueprint.verification import requirement_verdict

    reached = neighbourhood(doc, requirement_id)

    chain: dict[str, list[str]] = {}
    for artifact_id in sorted(reached):
        if not is_valid_id(artifact_id):
            continue
        prefix, _ = parse_id(artifact_id)
        chain.setdefault(prefix, []).append(artifact_id)
    for ids in chain.values():
        ids.sort(key=lambda i: parse_id(i)[1])

    files: list[str] = []
    for artifact_id in reached:
        files.extend(where(doc, artifact_id).files)

    verdict = requirement_verdict(doc, requirement_id)
    return Trace(
        requirement=requirement_id,
        chain=chain,
        files=tuple(dict.fromkeys(sorted(files))),
        verdict=verdict["result"],
        facets=verdict["facets"],
    )


def coverage(doc: dict) -> dict[str, Any]:
    """How much of the Blueprint has an implementation recorded (§21).

    A blunt count, and honest about being one: it says whether ``codeMap`` has
    an entry, not whether the entry is true. Checking entries against files on
    disk is ``Blueprint↔Implementation``'s job and ``verification.py`` states
    plainly that it does not do it either.
    """
    mapped = set(_index(doc))
    total: list[str] = []
    for section, art in graph_pool(doc):
        if section in ("codeMap", "requirements"):
            continue
        if art.get("id") and art.get("status") != "DEPRECATED":
            total.append(art["id"])
    covered = [a for a in total if a in mapped]
    return {
        "artifacts": len(total),
        "mapped": len(covered),
        "unmapped": sorted(set(total) - mapped),
        "ratio": round(len(covered) / len(total), 2) if total else 0.0,
    }

"""§8 layer 4 — where a Blueprint concept lives in the generated code.

Smith's memory has four layers and only three were reachable: conversation,
the Blueprint, and decisions. The fourth — "knowledge of where Blueprint
concepts exist in the generated implementation" — had no reader, so Smith could
say what the application *is* and not where any of it *went*.

The index already ships. `codeMap` is projected by the `backend` and `frontend`
projections and checked by the Blueprint<->Implementation edge, one entry per
artifact:

    {"artifact": "PAGE-001", "service": ["src/schemas/plants.json"]}
    {"artifact": "ENTITY-001", "entity": "ENTITY-001",
     "service": ["src/db/schema/plant.ts"]}

So this is a resolver over an artifact nobody read, not a new index. Both
directions matter and only one is obvious: `files_for` answers "where does
PAGE-001 live", and `artifacts_for` answers the reverse — which is what §113's
preview->Blueprint link, §115's divergence check and §7's "understand the
generated implementation" all need, and none of them can ask a forward-only
index.

File granularity, because that is the granularity `codeMap` records. §8 asks
where concepts *exist*, which a file answers; a caller wanting the symbol needs
a different index and should be told so rather than handed a guess.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Keys on a codeMap entry that hold paths. `artifact` and `entity` are the
#: entry's identity, not its contents, and adding either to the path set makes
#: an id look like a file to every consumer downstream.
_PATH_KEYS = ("service", "frontend", "backend", "test", "tests", "migration")


def _live(items: Any) -> list[dict]:
    """Entries that still count — a superseded one describes code that moved."""
    return [
        i
        for i in (items or [])
        if isinstance(i, dict) and i.get("status") != "SUPERSEDED"
    ]


def _paths(entry: dict) -> list[str]:
    out: list[str] = []
    for key in _PATH_KEYS:
        value = entry.get(key)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out.extend(str(v) for v in value if isinstance(v, (str,)))
    # Sorted and de-duplicated: a caller showing these to a person wants a
    # stable order, and two keys can legitimately name the same file.
    return sorted(set(out))


def files_for(doc: dict, artifact_id: str) -> list[str]:
    """Every file that implements `artifact_id`, or [] if nothing does.

    Empty is a real answer: an artifact the projections have not reached yet
    has no code, which is different from an artifact that does not exist.
    """
    return sorted(
        {
            path
            for entry in _live(doc.get("codeMap"))
            if entry.get("artifact") == artifact_id
            for path in _paths(entry)
        }
    )


def artifacts_for(doc: dict, path: str) -> list[str]:
    """Every Blueprint artifact `path` implements.

    The direction the forward index cannot serve. A file legitimately carries
    more than one artifact — a route file implements a page and the endpoint
    behind it — so this returns a list, and a caller that wants "the" artifact
    for a file is asking a question the data does not answer.
    """
    return sorted(
        {
            str(entry["artifact"])
            for entry in _live(doc.get("codeMap"))
            if entry.get("artifact") and path in _paths(entry)
        }
    )


def context_for(doc: dict, artifact_ids: Iterable[str]) -> dict[str, list[str]]:
    """`{artifact: files}` for several artifacts at once.

    §8's Context Resolver returns "only context relevant to the current
    request", and a request touches a handful of artifacts rather than one.
    Artifacts with no code are kept with an empty list — that a page exists and
    has not been generated is exactly the kind of thing Smith should be able to
    say.
    """
    return {aid: files_for(doc, aid) for aid in artifact_ids}


def unimplemented(doc: dict) -> list[str]:
    """Artifacts the Blueprint declares that no file implements.

    §115 says the platform must flag divergence rather than silently choosing a
    side. This is the cheap half of that: everything the Blueprint claims and
    the code does not have. The expensive half — code with no Blueprint behind
    it — needs a file walk, not this index.
    """
    implemented = {
        str(e["artifact"])
        for e in _live(doc.get("codeMap"))
        if e.get("artifact") and _paths(e)
    }
    declared: list[str] = []
    for section in ("pages", "workflows", "apis", "requirements"):
        declared += [
            str(a["id"]) for a in _live(doc.get(section)) if a.get("id")
        ]
    entities = (doc.get("data") or {}).get("entities")
    declared += [str(e["id"]) for e in _live(entities) if e.get("id")]
    return sorted(set(declared) - implemented)

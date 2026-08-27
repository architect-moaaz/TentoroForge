"""Detect related-data gaps on detail pages.

Motivation
----------
When a user says "the Drive detail page doesn't show all the information,"
they usually don't mean "you forgot to render one of Drive's columns" —
the schema already binds all columns. What they mean is: **the detail
page shows the entity in isolation, without the related data a reader
of that page would expect** (recruiter's name instead of UUID, list of
Applications tied to this drive, list of Interviews scheduled here).

Smith's current app-map tells it what pages exist and what schemas
render. It doesn't tell it "entity X has 3 inbound relationships;
its detail page currently renders 0 of them." So when asked to fix
this class of issue, Smith walks the schema, sees all Drive columns
bound, concludes "nothing missing," and asks the user to be more
specific. That's a context gap, not a Smith bug.

This module fills that gap. For each detail page in the app, it
compares:
  * Inbound relationships to the page's entity (things Y where
    Y.xId → X) — those are candidate "related data" sections.
  * FK columns rendered as raw UUIDs (bound as ``{{drive.recruiterId}}``
    without a join) — those should be joined to the target entity's
    display name.

Emits a compact ``detail_gaps`` list per detail page. Callers attach
it to the app-map so Smith sees it before it decides how to respond.

Contract
--------
``analyze_detail_pages(entities, pages, output_dir) -> list[DetailGaps]``

Each :class:`DetailGaps` entry names one detail page and lists the
inbound relations and FK joins that are NOT yet rendered in its
schema. Empty ``gaps`` means the detail page is already complete
for its relationship surface — no action needed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DetailGap:
    """One missing related-data section on a detail page."""
    kind: str                    # "inbound_relation" | "fk_join"
    related_entity: str          # e.g. "Application"
    related_via_column: str      # e.g. "driveId" (fk column on related side)
                                 # or the FK column ON THE PAGE'S entity for fk_join
    suggested_component: str     # e.g. "Table" | "Text"
    rationale: str               # one-line, Smith-readable


@dataclass
class DetailGaps:
    """A detail page + its list of gaps. Empty ``gaps`` = page is
    already relationship-complete."""
    route: str
    schema_path: str
    entity: str
    gaps: list[DetailGap] = field(default_factory=list)


def analyze_detail_pages(
    entities: dict[str, dict],
    pages: list[dict],
    output_dir: str | Path,
) -> list[DetailGaps]:
    """Return a list of ``DetailGaps`` — one per detail page found.

    Pages without an entity binding, or whose schema can't be parsed,
    are skipped (never raised). A page with zero gaps is still
    returned so Smith can prove it looked at every detail page.
    """
    root = Path(output_dir)
    out: list[DetailGaps] = []
    for page in pages:
        if page.get("archetype") != "detail":
            continue
        ent_name = page.get("entity")
        if not ent_name or ent_name not in entities:
            continue
        schema_rel = page.get("path")
        if not isinstance(schema_rel, str):
            continue

        gaps = DetailGaps(
            route=page["route"],
            schema_path=schema_rel,
            entity=ent_name,
        )
        schema_content = _read_schema_bindings(root / schema_rel)
        _find_inbound_gaps(entities, ent_name, schema_content, gaps.gaps)
        _find_fk_join_gaps(entities, ent_name, schema_content, gaps.gaps)
        out.append(gaps)
    return out


# ────────────────────────────────────────────────────────────
# Schema inspection
# ────────────────────────────────────────────────────────────

_BINDING_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\[\]]+)\s*\}\}")


def _read_schema_bindings(path: Path) -> dict[str, Any]:
    """Return ``{"raw_bindings": {...}, "data_sources": [...]}`` from a
    schema file, or empty stubs when the file can't be parsed.

    ``raw_bindings`` is the SET of expression paths the schema references
    via ``{{binding}}`` syntax. ``data_sources`` is the schema's own
    dataSources list (an entry means the schema already loads that
    entity, so a related-data section for it isn't a gap)."""
    try:
        content = path.read_text(encoding="utf-8")
        parsed = json.loads(content)
    except Exception:  # noqa: BLE001
        return {"raw_bindings": set(), "data_sources": []}
    return {
        "raw_bindings": set(_BINDING_RE.findall(content)),
        "data_sources": parsed.get("dataSources") or [],
    }


def _has_entity_source(schema: dict[str, Any], entity: str) -> bool:
    """True when the schema's dataSources already load ``entity``. Used
    to avoid flagging a gap for something the schema already fetches
    (even if it renders it in a way we don't recognise)."""
    for ds in schema.get("data_sources", []):
        if isinstance(ds, dict) and ds.get("entity") == entity:
            return True
    return False


# ────────────────────────────────────────────────────────────
# Gap rule 1 — inbound relations not rendered
# ────────────────────────────────────────────────────────────

def _find_inbound_gaps(
    entities: dict[str, dict],
    ent_name: str,
    schema: dict[str, Any],
    out: list[DetailGap],
) -> None:
    """For every ``Y.xId → X`` relationship into this page's entity X,
    flag a gap when the schema doesn't already load Y. That's the
    "detail page should show related Ys" class."""
    ent = entities.get(ent_name) or {}
    for inbound in ent.get("fks_in", []):
        related = inbound.get("from_entity")
        via = inbound.get("col")
        if not related or not via:
            continue
        if _has_entity_source(schema, related):
            continue
        out.append(DetailGap(
            kind="inbound_relation",
            related_entity=related,
            related_via_column=via,
            suggested_component="Table",
            rationale=(
                f"The {ent_name} detail page has no dataSource for "
                f"{related}, but {related}.{via} references {ent_name}. "
                f"A Table of {related} rows joined on {via}=id would be "
                "expected on this detail page."
            ),
        ))


# ────────────────────────────────────────────────────────────
# Gap rule 2 — FK column bound as raw UUID (no join)
# ────────────────────────────────────────────────────────────

def _find_fk_join_gaps(
    entities: dict[str, dict],
    ent_name: str,
    schema: dict[str, Any],
    out: list[DetailGap],
) -> None:
    """For every outbound FK column bound as ``{{ent.recruiterId}}``
    but with no join to the target entity, flag a gap. The user sees
    a UUID; they expect the target's display name."""
    ent = entities.get(ent_name) or {}
    var = ent_name[:1].lower() + ent_name[1:]
    for fk in ent.get("fks_out", []):
        target = fk.get("target_entity")
        col = fk.get("col")
        if not target or not col:
            continue
        # Raw FK binding present? (e.g. ``{{drive.recruiterId}}``)
        raw = f"{var}.{col}"
        if raw not in schema["raw_bindings"]:
            continue
        # Target-entity dataSource loaded? Then a join is possible in
        # principle and the schema is already set up for it — not a
        # gap for this pass.
        if _has_entity_source(schema, target):
            continue
        out.append(DetailGap(
            kind="fk_join",
            related_entity=target,
            related_via_column=col,
            suggested_component="Text",
            rationale=(
                f"The {ent_name} detail page renders "
                f"{{{{{raw}}}}} as a raw UUID. Joining to {target} "
                f"and rendering its display name would be more useful."
            ),
        ))


# ────────────────────────────────────────────────────────────
# Serialisation helper — for injecting into Smith's app-map
# ────────────────────────────────────────────────────────────

def to_dict(gap_list: list[DetailGaps]) -> list[dict]:
    """Turn dataclasses into plain dicts (JSON-safe) for embedding in
    the app-map or logging."""
    out = []
    for g in gap_list:
        out.append({
            "route": g.route,
            "schema_path": g.schema_path,
            "entity": g.entity,
            "gaps": [
                {
                    "kind": gp.kind,
                    "related_entity": gp.related_entity,
                    "related_via_column": gp.related_via_column,
                    "suggested_component": gp.suggested_component,
                    "rationale": gp.rationale,
                }
                for gp in g.gaps
            ],
        })
    return out

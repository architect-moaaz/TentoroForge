"""Flag pages whose dataSource shape diverges from their archetype peers.

Motivation
----------
The Drive detail bug that broke this session's UX ("only drive.id is
rendering — everything else empty") was invisible to Smith because its
context showed the schema's *bindings* and *relationships* per page,
but not the *shape of dataSources across pages of the same archetype*.
Three sibling detail pages used ``{op: "get"}`` bare; ``/drives/[id]``
used ``{op: "get", filter: {...}}``. That extra ``filter`` clause
broke the fetch. From a single-page inspection nothing looked wrong.

This module scans every page in the app-map, groups them by
``archetype``, computes the modal dataSource *shape* per group, and
flags any page whose shape diverges from its peers. The result gets
attached to the app-map so Smith reads it before it reasons about
"the X page is empty" asks.

Shape signature
---------------
A dataSource's *shape signature* is the sorted tuple of its top-level
key names, keyed by its ``op``. Two dataSources share a signature iff
they use the same op AND declare the same set of surrounding keys.
That's coarse enough to survive naming/entity differences (three list
pages for different entities share a shape) and fine enough to catch
divergence (adding a rogue ``filter`` breaks the signature).

Rationale
---------
This is *inductive* detection — we don't know a priori what "the right
shape" is. We know it's whatever the majority of peers use. The
approach fails gracefully in two directions:
  * If EVERY page has the same anomalous shape, nothing gets flagged
    (correct — there's no signal to say it's wrong).
  * If EVERY page has a different shape (rare, chaotic app), no modal
    shape exists and everything is silently ignored (better than
    flagging nine things that all look "different").
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ShapeInconsistency:
    """One page whose dataSource shape diverges from its archetype peers."""
    route: str
    schema_path: str
    archetype: str
    data_source_name: str
    op: str
    observed_shape: list[str]     # e.g. ["entity", "filter", "name", "op"]
    peer_shape: list[str]         # e.g. ["entity", "name", "op"]
    peer_pages: list[str]         # a few routes that share the peer shape
    rationale: str                # Smith-readable one-liner


def find_peer_shape_inconsistencies(
    pages: list[dict],
    output_dir: str | Path,
) -> list[ShapeInconsistency]:
    """Compare each page's dataSource shape against its archetype's mode.

    Only checks pages with schemas we can parse and dataSources whose
    ``op`` is a string. Archetype groups with fewer than 3 members are
    skipped (no reliable mode — anything reads as "different"). Silent
    on any error; never raises.
    """
    root = Path(output_dir)

    # Load every page's schema once. Skip on parse failure.
    parsed: list[dict[str, Any]] = []
    for page in pages or []:
        rel = page.get("path")
        archetype = page.get("archetype")
        if not isinstance(rel, str) or not isinstance(archetype, str):
            continue
        try:
            schema = json.loads((root / rel).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        parsed.append({
            "route": page.get("route"),
            "path": rel,
            "archetype": archetype,
            "schema": schema,
        })

    # Group all dataSources by (archetype, op) and count signatures.
    # `groups[(archetype, op)]` -> list of {route, path, name, shape}.
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in parsed:
        arch = p["archetype"]
        sources = p["schema"].get("dataSources")
        if not isinstance(sources, list):
            continue
        for ds in sources:
            if not isinstance(ds, dict):
                continue
            op = ds.get("op")
            if not isinstance(op, str):
                continue
            shape = _shape_signature(ds)
            groups.setdefault((arch, op), []).append({
                "route": p["route"],
                "path": p["path"],
                "name": ds.get("name") or "",
                "shape": shape,
            })

    inconsistencies: list[ShapeInconsistency] = []
    for (arch, op), entries in groups.items():
        # Need at least 3 members to have a reliable modal shape.
        if len(entries) < 3:
            continue
        shape_counts = Counter(tuple(e["shape"]) for e in entries)
        modal_shape, modal_n = shape_counts.most_common(1)[0]
        # If the mode is a bare majority (not a strong one), skip too —
        # a 2/4 vs 2/4 split has no signal.
        if modal_n <= len(entries) // 2:
            continue
        # Everything that isn't the modal shape is an anomaly.
        peer_routes = [e["route"] for e in entries
                       if tuple(e["shape"]) == modal_shape][:3]
        for e in entries:
            if tuple(e["shape"]) == modal_shape:
                continue
            diff_added = sorted(set(e["shape"]) - set(modal_shape))
            diff_missing = sorted(set(modal_shape) - set(e["shape"]))
            rationale = _rationale(op, arch, diff_added, diff_missing,
                                   peer_routes)
            inconsistencies.append(ShapeInconsistency(
                route=e["route"],
                schema_path=e["path"],
                archetype=arch,
                data_source_name=e["name"],
                op=op,
                observed_shape=list(e["shape"]),
                peer_shape=list(modal_shape),
                peer_pages=peer_routes,
                rationale=rationale,
            ))
    return inconsistencies


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _shape_signature(ds: dict) -> list[str]:
    """Sorted list of top-level dataSource keys. Order-independent.

    Values are ignored — a shape signature is about STRUCTURE, not
    content. Two dataSources with the same keys but different filter
    values are the same shape.
    """
    return sorted(str(k) for k in ds.keys() if isinstance(k, str))


def _rationale(
    op: str,
    archetype: str,
    added: list[str],
    missing: list[str],
    peer_routes: list[str],
) -> str:
    """One-line Smith-readable explanation of the divergence."""
    parts = []
    if added:
        parts.append(f"has extra keys ({', '.join(added)})")
    if missing:
        parts.append(f"is missing keys ({', '.join(missing)})")
    diff = " and ".join(parts) if parts else "differs in shape"
    peers = ", ".join(peer_routes) if peer_routes else "peer pages"
    return (
        f"This {archetype} page's ``{op}`` dataSource {diff} "
        f"compared to peer {archetype} pages ({peers}). If the page "
        f"renders empty or partially bound, the extra/missing keys are "
        "the likely cause."
    )


def to_dict(items: list[ShapeInconsistency]) -> list[dict]:
    """JSON-safe form for embedding in the app-map."""
    return [
        {
            "route": i.route,
            "schema_path": i.schema_path,
            "archetype": i.archetype,
            "data_source_name": i.data_source_name,
            "op": i.op,
            "observed_shape": i.observed_shape,
            "peer_shape": i.peer_shape,
            "peer_pages": i.peer_pages,
            "rationale": i.rationale,
        }
        for i in items
    ]

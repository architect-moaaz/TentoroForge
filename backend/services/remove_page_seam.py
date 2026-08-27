"""Composite seam — remove a page (and, on request, its whole feature slice).

Symmetrical to :mod:`services.add_page_seam`. Removes the schema JSON for a
route (or every archetype under that route base — list / new / [id] /
[id]/edit), strips matching nav-flow entries + transitions, and delegates
registry.ts + shell.json regeneration to the caller's post-apply hook so
the tree stays consistent with what the app dispatcher actually loads.

Contract
--------
``build_remove_page_bundle(output_dir, route, *, cascade=False)`` — returns
a list of :class:`BundleOp` deletions/rewrites. If ``cascade=True``, every
archetype under the route base (``/x`` + ``/x/new`` + ``/x/[id]`` +
``/x/[id]/edit`` + any nested schema whose route starts with ``/x/``)
is removed together — the whole feature area, in one atomic transaction.

Raises :class:`RemovePageError` if the route is invalid, if no schema files
match, or if the nav-flow can't be parsed. Success means at least one
schema file was slated for deletion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from services.atomic_apply import BundleOp


class RemovePageError(Exception):
    """Raised when the seam can't compute a valid removal bundle."""


@dataclass
class _MatchedFile:
    schema_path: str    # e.g. "src/schemas/recruiters/new.json"
    route: str          # e.g. "/recruiters/new"


def build_remove_page_bundle(
    output_dir: str,
    route: str,
    *,
    cascade: bool = False,
) -> list[BundleOp]:
    """Compose the atomic bundle to remove one route (or the whole feature).

    ``cascade=False``: remove only the schema at exactly ``route``.
    ``cascade=True``:  remove ``route`` plus every schema whose derived
                       route starts with ``route + "/"`` — the "remove
                       the whole recruiter area" case.
    """
    if not isinstance(route, str) or not route.startswith("/"):
        raise RemovePageError(f"invalid route {route!r}: must start with '/'")

    out = Path(output_dir)
    if not out.exists():
        raise RemovePageError(f"output dir does not exist: {output_dir}")

    schemas_dir = out / "src" / "schemas"
    if not schemas_dir.exists():
        raise RemovePageError("no src/schemas/ dir — nothing to remove")

    matched = _find_matching(schemas_dir, route, cascade=cascade)
    if not matched:
        raise RemovePageError(
            f"no schema files match route {route!r} "
            f"(cascade={cascade}) — nothing to remove"
        )

    # 1) Schema file deletions.
    ops: list[BundleOp] = []
    for m in matched:
        ops.append(BundleOp(path=m.schema_path, content="", kind="delete"))

    # 2) Nav-flow rewrite — strip page entries + transitions for every
    # matched route in one op so the applier reconciles it once.
    nav_flow_rel = "src/contracts/nav-flow.json"
    nav_flow_path = out / nav_flow_rel
    if nav_flow_path.exists():
        try:
            nav = json.loads(nav_flow_path.read_text())
        except Exception as exc:  # noqa: BLE001
            raise RemovePageError(f"nav-flow parse failed: {exc}") from exc
        dead_routes = {m.route for m in matched}
        pages = nav.get("pages") or []
        nav["pages"] = [
            p for p in pages
            if not (isinstance(p, dict) and p.get("route") in dead_routes)
        ]
        trans = nav.get("transitions")
        if isinstance(trans, list):
            nav["transitions"] = [
                t for t in trans
                if isinstance(t, dict)
                and t.get("from") not in dead_routes
                and t.get("to") not in dead_routes
            ]
        ops.append(BundleOp(
            path=nav_flow_rel,
            content=json.dumps(nav, indent=2) + "\n",
            kind="nav-flow",
        ))

    return ops


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _find_matching(
    schemas_dir: Path, route: str, *, cascade: bool
) -> list[_MatchedFile]:
    """Scan src/schemas/**/*.json, return the files whose derived route
    equals ``route`` (or, with cascade, is nested under it)."""
    from services.route_slug import route_from_slug

    matches: list[_MatchedFile] = []
    prefix = route.rstrip("/") + "/"
    for json_file in sorted(schemas_dir.rglob("*.json")):
        if json_file.name in ("registry.json", "load.json", "shell.json"):
            continue
        rel = json_file.relative_to(schemas_dir)
        slug = str(rel.with_suffix("")).replace("\\", "/")
        try:
            derived = route_from_slug(slug)
        except Exception:  # noqa: BLE001
            continue
        if derived == route or (cascade and derived.startswith(prefix)):
            rel_from_project = "src/schemas/" + str(rel).replace("\\", "/")
            matches.append(_MatchedFile(
                schema_path=rel_from_project,
                route=derived,
            ))
    return matches

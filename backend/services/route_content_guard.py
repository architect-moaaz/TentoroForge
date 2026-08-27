"""Detect (and log) when a page's schema content doesn't match its route.

Bug 3 in the cabin-crew ATS: the ``/notifications`` route rendered a Users
list — a "New User" button and columns like Email/Name/Role — because
``page_schema_agent`` wrote off-domain content into that route's slot.
There was no signal downstream that the route was mislabeled: the schema
validated, the renderer resolved bindings, everything ran; the LLM had
just written the wrong page for the URL.

This guard is a **deterministic mismatch detector**. It doesn't repair —
repair on off-domain content is dangerous (destroying the LLM's work
without a strong replacement is usually worse than the original). It
LOGS every mismatch it finds so the pipeline reliability atlas can grow
with real signal, and returns a report the caller can act on.

Rule: for every emitted schema at route ``/<noun>[/...]`` where ``<noun>``
maps to a known entity in the registry, the schema's primary dataSource
MUST reference that entity (or a plausible variant of it). If not, we
flag ``off_route_entity`` with the observed entity vs. the expected one.

Excluded (never flagged):
  * Non-entity routes: ``/dashboard``, ``/settings``, ``/home``, ``/`` etc.
    — those aren't backed by one entity and can legitimately aggregate
    across many.
  * Auth pages: ``/login``, ``/signup``.
  * Dynamic-segment children: ``/candidates/[id]`` isn't checked against
    "candidates" strictly — its dataSource may be an aggregate.

Rationale for warn-not-fix: the correct repair is usually
"regenerate this schema with a stronger prompt anchored to the route's
noun." That's a page_schema_agent slice, not a post-guard one. This
module surfaces the signal so we know when to fire that slice.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.entity_names import try_derive_names

log = logging.getLogger(__name__)

# Routes that legitimately aggregate across entities — no single-entity
# check applies.
_NON_ENTITY_ROUTES = {
    "/", "/dashboard", "/home", "/settings", "/login", "/signup",
    "/account", "/profile",
}


def check_route_content(output_dir: str | Path) -> dict:
    """Scan every emitted schema for route-content mismatches.

    Returns a dict:
      * ``mismatches`` — list of ``{route, expected_entity, observed_entity, schema_file}``
      * ``checked``    — count of schemas inspected
      * ``skipped``    — count of schemas skipped (non-entity routes, etc.)
    """
    base = Path(output_dir)
    schemas = base / "src" / "schemas"
    reg = base / "registry.json"
    if not schemas.is_dir() or not reg.is_file():
        return {"mismatches": [], "checked": 0, "skipped": 0}

    try:
        entities = (json.loads(reg.read_text(encoding="utf-8")).get("entities") or {})
    except Exception:  # noqa: BLE001
        return {"mismatches": [], "checked": 0, "skipped": 0}
    if not entities:
        return {"mismatches": [], "checked": 0, "skipped": 0}
    ent_index = _entity_index(entities)

    mismatches: list[dict] = []
    checked = 0
    skipped = 0
    for f in sorted(schemas.rglob("*.json")):
        base_name = f.name
        if base_name in ("shell.json", "nav-flow.json"):
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = _route_for_schema(f, doc, schemas)
        if not route:
            continue
        expected_ent = _expected_entity(route, ent_index)
        if not expected_ent:
            skipped += 1
            continue
        observed_ent = _primary_entity(doc)
        checked += 1
        if not observed_ent:
            continue   # no dataSources at all — a plain content page
        if _entity_key(observed_ent) == _entity_key(expected_ent):
            continue
        mismatches.append({
            "route": route,
            "expected_entity": expected_ent,
            "observed_entity": observed_ent,
            "schema_file": str(f.relative_to(base)),
        })
        log.warning(
            "[route-content] mismatch at %s: expected entity=%s, got %s (schema=%s)",
            route, expected_ent, observed_ent, f.relative_to(base),
        )
    return {"mismatches": mismatches, "checked": checked, "skipped": skipped}


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _entity_key(name: str) -> str:
    """Fold to a comparable key: lowercase, strip non-alphanumerics."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _entity_index(entities: dict) -> dict[str, str]:
    """Build a lookup ``{lowered-noun: canonical-entity-name}`` covering
    both singular and plural forms of each entity's name.

    So ``notifications`` (plural in URL) and ``notification`` (singular
    entity) both map to ``"Notification"``.
    """
    out: dict[str, str] = {}
    for name in entities.keys():
        low = name.lower()
        out[low] = name
        # Naive plural: entity ``Notification`` → ``notifications``
        out[low + "s"] = name
        # Handle "-y" → "-ies" (Category → categories, City → cities)
        if low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
            out[low[:-1] + "ies"] = name
        # Handle "-s", "-x", "-ch" → "-es"
        if low.endswith(("s", "x", "ch", "sh")):
            out[low + "es"] = name
        # snake_case variants
        out[low.replace("_", "-")] = name

        # The spellings the rest of the pipeline actually emits, straight
        # from the single naming authority. The hand-rolled rules above are
        # KEPT — this index is deliberately tolerant, and every alias only
        # widens what resolves — but they are not what any generator uses,
        # so a route named off the canonical slug used to miss.
        names = try_derive_names(name)
        if names is not None:
            for alias in (names.routeSlug, names.pluralSlug, names.tableSnake,
                          names.sourceName.lower(), names.entityKey):
                out.setdefault(alias, name)
        else:
            log.error(
                "route_content_guard: entity %r has no derivable name variants; "
                "routes spelled the canonical way will not resolve to it", name,
            )
    return out


def _route_for_schema(f: Path, doc: dict, schemas_root: Path) -> str | None:
    """Return the route this schema serves. Prefer the ``route`` field in
    the JSON when present; otherwise derive from filename layout."""
    r = doc.get("route")
    if isinstance(r, str) and r.startswith("/"):
        return r
    rel = f.relative_to(schemas_root).with_suffix("")
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    return "/" + "/".join(parts) if parts else None


def _expected_entity(route: str, ent_index: dict[str, str]) -> str | None:
    """The entity the FIRST segment of ``route`` implies, if any.

    Only checks top-level LIST routes (one segment: ``/notifications``,
    ``/candidates``, ``/drives``). Dynamic-segment routes like
    ``/candidates/[id]`` and their descendants may legitimately bind to
    a different entity (an application list under a candidate detail),
    so we don't flag them here.
    """
    if route in _NON_ENTITY_ROUTES:
        return None
    parts = [p for p in route.strip("/").split("/") if p]
    if len(parts) != 1:
        return None    # only single-segment list routes get checked
    first = parts[0]
    if first.startswith("["):
        return None
    return ent_index.get(first.lower())


def _primary_entity(doc: dict) -> str | None:
    """The entity name from the schema's first ``dataSources`` entry.

    We treat the first dataSource as "primary" because it's the one the
    page's main content typically binds to — a Table, a Card, a header.
    """
    ds_list = doc.get("dataSources")
    if not isinstance(ds_list, list):
        return None
    for ds in ds_list:
        if isinstance(ds, dict):
            ent = ds.get("entity")
            if isinstance(ent, str) and ent.strip():
                return ent
    return None

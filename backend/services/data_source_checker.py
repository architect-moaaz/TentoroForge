"""Check a single page's dataSources for shape / reference errors.

The runtime cure for the class of bug Slice 12A detected inductively —
this module encodes the deductive rules per ``op`` so Smith can inspect
a single page and get a straight answer:

  * ``op="get"`` — fetches by URL params. Extra ``filter`` clauses break
    the fetch (the Drive-detail bug).
  * ``op="list"`` — accepts ``filter``, ``sort``, ``limit``, ``search``.
    ``where`` is not a runtime key (peer pages use ``filter``).
  * ``op="aggregate"`` — needs ``metrics``.
  * ``op="series"`` — needs ``groupBy`` and ``metric``.
  * ``op="readOne"`` / ``op="one"`` — needs ``where``.

Every dataSource is also checked against the resource registry:
  * ``entity`` must resolve to a real entity (either its declared name
    or its slug).

Peer-shape hints from :mod:`services.peer_shape_analyzer` are attached
for the requested page so Smith sees both the deductive rule AND the
inductive divergence in one payload.

This is a *pure* inspection — never mutates disk, never raises. On any
IO/parse failure it returns a payload that says so.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ────────────────────────────────────────────────────────────
# Deductive rules per op
# ────────────────────────────────────────────────────────────

# Keys allowed alongside {name, entity, op} for each op. Anything a page
# declares outside of this set + the required set is flagged. The
# baseline (name/entity/op) is always allowed and never listed here.
_ALLOWED_KEYS: dict[str, set[str]] = {
    "get":       set(),
    "list":      {"filter", "sort", "limit", "offset", "search", "pageSize"},
    "aggregate": {"metrics", "groupBy", "filter"},
    "series":    {"groupBy", "metric", "filter", "orderBy", "limit"},
    "readone":   {"where"},
    "one":       {"where"},
}

# Keys REQUIRED per op — missing them is flagged even without a peer.
_REQUIRED_KEYS: dict[str, set[str]] = {
    "aggregate": {"metrics"},
    "series":    {"groupBy", "metric"},
    "readone":   {"where"},
    "one":       {"where"},
}

# ``get`` explicitly cannot carry a filter — call it out with a targeted
# message rather than the generic "extra key" one.
_EXPLICIT_BAD_KEYS: dict[str, dict[str, str]] = {
    "get": {
        "filter": (
            "``op:\"get\"`` fetches by URL params (the ``[id]`` segment); "
            "an extra ``filter`` clause breaks the fetch and is the "
            "canonical cause of a detail page rendering only its id."
        ),
        "where": (
            "``op:\"get\"`` uses URL params, not a ``where`` clause. "
            "Remove ``where``; the id already comes from the route."
        ),
    },
    "list": {
        "where": (
            "``op:\"list\"`` uses ``filter``, not ``where``. Rename "
            "``where`` to ``filter`` to match peer list pages."
        ),
    },
}


@dataclass
class Violation:
    """One issue with one dataSource on a page."""
    kind: str                     # e.g. "extra_key", "missing_key", "unknown_entity"
    data_source_name: str
    op: str
    key: str | None = None        # the offending key, when applicable
    message: str = ""             # Smith-readable one-liner


@dataclass
class DataSourceCheck:
    path: str
    route: str
    data_sources: list[dict] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    peer_hints: list[dict] = field(default_factory=list)
    error: str | None = None


# ────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────

def check_data_source(output_dir: str | Path, path: str) -> dict[str, Any]:
    """Load the schema at ``path`` (relative to ``output_dir``) and check
    every dataSource on it. Returns a JSON-safe dict.

    Never raises. Missing/unparseable files return an ``error`` field
    instead of throwing so Smith can surface the failure verbatim.
    """
    root = Path(output_dir)
    check = DataSourceCheck(path=path, route="?")

    schema_file = root / path
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        check.error = f"page schema not found: {path}"
        return _to_dict(check)
    except Exception as exc:  # noqa: BLE001
        check.error = f"page schema unreadable: {exc}"
        return _to_dict(check)

    check.route = str(schema.get("route") or "?")
    sources = schema.get("dataSources")
    if not isinstance(sources, list):
        check.error = "page has no dataSources array"
        return _to_dict(check)

    known_entities = _load_known_entities(root)

    for ds in sources:
        if not isinstance(ds, dict):
            continue
        summary = {
            "name":   ds.get("name") or "",
            "entity": ds.get("entity") or "",
            "op":     ds.get("op") or "",
        }
        # Include the surrounding keys so Smith sees exactly what the
        # schema author declared without a second read_page.
        summary["keys"] = sorted(str(k) for k in ds.keys())
        check.data_sources.append(summary)

        op_raw = ds.get("op")
        if not isinstance(op_raw, str):
            check.violations.append(Violation(
                kind="missing_op",
                data_source_name=summary["name"],
                op="",
                message=(
                    "dataSource is missing an ``op`` — every dataSource "
                    "must declare one of get/list/aggregate/series/"
                    "readOne."
                ),
            ))
            continue
        op_norm = op_raw.lower()

        # 1. Entity resolves against the registry?
        entity_raw = ds.get("entity")
        if isinstance(entity_raw, str) and entity_raw and known_entities:
            if not _entity_matches(entity_raw, known_entities):
                check.violations.append(Violation(
                    kind="unknown_entity",
                    data_source_name=summary["name"],
                    op=op_raw,
                    key="entity",
                    message=(
                        f"entity {entity_raw!r} does not match any "
                        f"registered entity name or slug. Check "
                        f"list_entities and pick a real one."
                    ),
                ))

        # 2. Required keys per op?
        required = _REQUIRED_KEYS.get(op_norm, set())
        for key in sorted(required - set(ds.keys())):
            check.violations.append(Violation(
                kind="missing_key",
                data_source_name=summary["name"],
                op=op_raw,
                key=key,
                message=(
                    f"``op:{op_raw!r}`` requires a ``{key}`` field; the "
                    f"runtime cannot build this query without it."
                ),
            ))

        # 3. Explicit bad keys (targeted messages).
        explicit = _EXPLICIT_BAD_KEYS.get(op_norm, {})
        seen_explicit = set()
        for key, message in explicit.items():
            if key in ds:
                check.violations.append(Violation(
                    kind="extra_key",
                    data_source_name=summary["name"],
                    op=op_raw,
                    key=key,
                    message=message,
                ))
                seen_explicit.add(key)

        # 4. Anything else outside the allowed set for this op.
        allowed = _ALLOWED_KEYS.get(op_norm)
        if allowed is not None:
            baseline = {"name", "entity", "op"}
            for key in sorted(set(ds.keys()) - allowed - baseline):
                if key in seen_explicit:
                    continue
                check.violations.append(Violation(
                    kind="extra_key",
                    data_source_name=summary["name"],
                    op=op_raw,
                    key=key,
                    message=(
                        f"``{key}`` is not a recognized key for "
                        f"``op:{op_raw!r}``. Allowed keys: "
                        f"{sorted(allowed) or '(none)'}."
                    ),
                ))

    # Peer hints — piggyback the whole app-map's inductive result.
    check.peer_hints = _peer_hints_for_path(root, path)

    return _to_dict(check)


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _load_known_entities(root: Path) -> list[dict]:
    """Read the resource registry's entities if available. Silent on
    absence — a missing registry just means we skip the entity check."""
    reg_path = root / "contracts" / "resource-registry.json"
    if not reg_path.exists():
        reg_path = root / "resource-registry.json"
    if not reg_path.exists():
        return []
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    ents = reg.get("entities")
    if isinstance(ents, list):
        return [e for e in ents if isinstance(e, dict)]
    if isinstance(ents, dict):
        return [
            {"name": name, **(meta if isinstance(meta, dict) else {})}
            for name, meta in ents.items()
        ]
    return []


def _norm(s: str | None) -> str:
    return (s or "").strip().lower().replace("_", "").replace("-", "")


def _entity_matches(entity: str, known: list[dict]) -> bool:
    target = _norm(entity)
    for e in known:
        if _norm(e.get("name")) == target:
            return True
        if _norm(e.get("slug")) == target:
            return True
        if _norm(e.get("table")) == target:
            return True
    return False


def _peer_hints_for_path(root: Path, path: str) -> list[dict]:
    """Ask the peer-shape analyzer about this specific page's inconsistencies.

    Reuses the same signal Slice 12A attaches to the app-map, but scoped
    to one path so Smith gets an immediate, single-file answer.
    """
    try:
        from services.app_map import build_app_map
        from services.peer_shape_analyzer import (
            find_peer_shape_inconsistencies,
            to_dict as peer_to_dict,
        )
        app_map = build_app_map(root)
        incs = find_peer_shape_inconsistencies(app_map.get("pages") or [], root)
        matched = [i for i in incs if getattr(i, "schema_path", None) == path]
        return peer_to_dict(matched)
    except Exception:  # noqa: BLE001
        return []


def _to_dict(check: DataSourceCheck) -> dict:
    payload = {
        "path":         check.path,
        "route":        check.route,
        "dataSources":  check.data_sources,
        "violations": [
            {
                "kind":              v.kind,
                "data_source_name":  v.data_source_name,
                "op":                v.op,
                "key":               v.key,
                "message":           v.message,
            }
            for v in check.violations
        ],
        "peer_hints":  check.peer_hints,
    }
    if check.error:
        payload["error"] = check.error
    return payload

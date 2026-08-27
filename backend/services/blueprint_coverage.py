"""Blueprint coverage gate.

Walks the emitted app tree and asks a simple question of every
authoring artifact: *does the current* ``BLUEPRINT.md`` *reference
this?* Anything that lives on disk but doesn't show up anywhere in
the blueprint is an "orphan" — a page nobody linked to, a Drizzle
table nobody documented, a workflow file the plan never mentions.

Emits a compact report the builder splices into the blueprint as
``## Uncovered Artifacts`` — an empty list there is a positive health
signal.

Design principles
-----------------

* **Never crash.** Missing files, malformed JSON, and unusual layouts
  all degrade to "we couldn't check that category" rather than raising.
* **Deterministic + cheap.** Regex-parse for Drizzle tables (no TS
  compilation) and glob-walk for schemas / workflows. The whole check
  runs in milliseconds even on ~50-entity apps.
* **Two-sided.** :func:`check_coverage` reads sources fresh; it is
  suitable for endpoint/CI use. :func:`check_coverage_from_sources`
  takes an already-loaded ``_Sources`` bundle so the builder can call
  it during ``build_blueprint`` without re-reading contracts.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

def check_coverage(output_dir: str | Path) -> dict:
    """Report which pages / tables / workflows / entities / routes exist on
    disk but aren't referenced in ``<output_dir>/BLUEPRINT.md``.

    Shape::

        {
          "covered": <int>,
          "uncovered": {
            "pages":     [<schema-file rel path>, ...],
            "tables":    [<table name>, ...],
            "workflows": [<workflow name>, ...],
            "entities":  [<entity name>, ...],
            "routes":    [<route>, ...],
          },
          "coverage_pct": <float 0..100>,
        }

    Missing BLUEPRINT.md means every artifact is uncovered (0%). Missing
    output_dir returns an empty report with pct=100 — there's nothing
    to be uncovered."""
    root = Path(output_dir)
    if not root.is_dir():
        return _empty_report()
    # Build the source bundle the same way the builder does, so both
    # sides see identical inputs.
    from services.blueprint_builder import _load_sources  # noqa: PLC0415
    sources = _load_sources(root)
    return check_coverage_from_sources(root, sources)


def check_coverage_from_sources(
    root: Path, sources: Any, *, blueprint_text: str | None = None,
) -> dict:
    """Same as :func:`check_coverage` but takes an already-loaded
    ``_Sources`` object. Used by ``build_blueprint`` to avoid re-reading
    every contract when it also emits the coverage section.

    ``blueprint_text`` overrides the on-disk read — the builder passes
    the in-progress body so the coverage check reflects what THIS
    build will render (not what the OLD file on disk contained).
    Callers that want the on-disk view (endpoints, ad-hoc checks) omit
    this and the function falls back to :func:`_read_blueprint`.
    """
    root = Path(root)
    if blueprint_text is None:
        blueprint_text = _read_blueprint(root)
    else:
        blueprint_text = _strip_uncovered_section(blueprint_text)

    # ---- gather on-disk artifacts ---------------------------------------
    pages = _list_page_schemas(root)
    tables = _list_drizzle_tables(root)
    workflows = _list_workflows(root, sources)
    entities = _list_entities(sources)
    routes = _list_routes(sources)

    # ---- decide which are uncovered -------------------------------------
    def _uncov(items: list[str]) -> list[str]:
        out: list[str] = []
        for item in items:
            if not _is_referenced(item, blueprint_text):
                out.append(item)
        return out

    # Pages: reference matches the schema file path (``src/schemas/…``)
    # OR the bare basename (schemas usually appear in headings by route).
    uncov_pages: list[str] = []
    for schema_file in pages:
        stem = Path(schema_file).stem
        route = _derive_route(schema_file, sources)
        alt_refs = [x for x in (stem, route) if x]
        if not _is_referenced(schema_file, blueprint_text, extras=alt_refs):
            uncov_pages.append(schema_file)

    # Tables: SQL names are snake_case_plural; the blueprint's Data Model
    # section renders entities by their CamelCase singular. Try both
    # forms before flagging as uncovered so a well-named table is
    # correctly matched to its entity.
    uncov_tables: list[str] = []
    for tbl in tables:
        alts = _table_name_variants(tbl)
        if not _is_referenced(tbl, blueprint_text, extras=alts):
            uncov_tables.append(tbl)

    uncov_workflows = _uncov(workflows)
    uncov_entities = _uncov(entities)
    uncov_routes = _uncov(routes)

    uncovered = {
        "pages": uncov_pages,
        "tables": uncov_tables,
        "workflows": uncov_workflows,
        "entities": uncov_entities,
        "routes": uncov_routes,
    }

    total = (
        len(pages) + len(tables) + len(workflows)
        + len(entities) + len(routes)
    )
    total_uncov = sum(len(v) for v in uncovered.values())
    covered = total - total_uncov
    pct = 100.0 if total == 0 else round((covered / total) * 100.0, 1)

    return {
        "covered": covered,
        "uncovered": uncovered,
        "coverage_pct": pct,
    }


# --------------------------------------------------------------------------- #
# Scanners — read the on-disk tree
# --------------------------------------------------------------------------- #

# ``pgTable("name", …)`` — the drizzle-orm SQL table declaration.
# We accept either quote style; the first capture group is the SQL table
# name (which is what the "## Data Model" section renders).
_PGTABLE_RE = re.compile(
    r"\bpgTable\s*\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
)


def _list_page_schemas(root: Path) -> list[str]:
    """Return ``src/schemas/…json`` rel-paths (posix) for every page
    schema file."""
    base = root / "src" / "schemas"
    if not base.is_dir():
        return []
    out: list[str] = []
    for p in sorted(base.rglob("*.json")):
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        out.append(rel)
    return out


def _list_drizzle_tables(root: Path) -> list[str]:
    """Every SQL table declared via ``pgTable("name", …)`` in
    ``src/db/schema/**/*.ts`` OR ``src/lib/db/schema.ts`` (either layout
    is possible depending on generation profile)."""
    candidates: list[Path] = []
    for rel in ("src/db/schema", "src/lib/db"):
        p = root / rel
        if p.is_dir():
            candidates.extend(sorted(p.rglob("*.ts")))
    # Also the single-file layout: src/lib/db/schema.ts specifically.
    solo = root / "src" / "lib" / "db" / "schema.ts"
    if solo.is_file() and solo not in candidates:
        candidates.append(solo)

    tables: list[str] = []
    seen: set[str] = set()
    for p in candidates:
        # Skip Forge-internal declaration files entirely — the platform
        # generates these (workflow_tasks, workflow_execution_log,
        # forge_files, …); they are not part of the app the user
        # authored, so they don't belong in the coverage denominator.
        if p.name.startswith("_forge_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _PGTABLE_RE.finditer(text):
            name = m.group(1)
            # Belt-and-braces: skip forge_* even if some non-forge file
            # happens to declare one.
            if name.startswith("_forge_") or name.startswith("forge_"):
                continue
            if name in seen:
                continue
            seen.add(name)
            tables.append(name)
    return tables


def _list_workflows(root: Path, sources: Any) -> list[str]:
    """Every workflow name — from the two possible on-disk directories
    PLUS the plan's ``workflows`` list (a workflow the plan promised
    but the file was never generated should also be surfaced)."""
    names: list[str] = []
    seen: set[str] = set()

    def _push(name: str) -> None:
        n = str(name or "").strip()
        if not n or n in seen:
            return
        seen.add(n)
        names.append(n)

    # File-based workflows.
    for wf_name in (sources.workflows or {}).keys():
        _push(wf_name)

    # Plan-listed workflows (may not have a file yet, or may have been
    # renamed since generation).
    plan = getattr(sources, "plan", {}) or {}
    plan_wfs = plan.get("workflows") or []
    if isinstance(plan_wfs, list):
        for w in plan_wfs:
            if isinstance(w, dict):
                _push(w.get("name") or "")
            elif isinstance(w, str):
                _push(w)
    return names


def _list_entities(sources: Any) -> list[str]:
    """Entity names from the plan (canonical). Falls back to the
    resource registry."""
    names: list[str] = []
    seen: set[str] = set()

    def _push(name: str) -> None:
        n = str(name or "").strip()
        if not n or n in seen:
            return
        seen.add(n)
        names.append(n)

    plan = getattr(sources, "plan", {}) or {}
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for n in ents.keys():
            _push(n)
    elif isinstance(ents, list):
        for rec in ents:
            if isinstance(rec, dict):
                _push(rec.get("name") or "")
            elif isinstance(rec, str):
                _push(rec)

    rr = getattr(sources, "resource_registry", {}) or {}
    rr_ents = rr.get("entities")
    if isinstance(rr_ents, dict):
        for n in rr_ents.keys():
            _push(n)
    return names


def _list_routes(sources: Any) -> list[str]:
    """Routes from ``nav-flow.json``. Fallback: root ``navigation.json``
    screens."""
    routes: list[str] = []
    seen: set[str] = set()

    def _push(r: str) -> None:
        r = str(r or "").strip()
        if not r or r in seen:
            return
        seen.add(r)
        routes.append(r)

    nf = getattr(sources, "nav_flow", {}) or {}
    for p in nf.get("pages") or []:
        if isinstance(p, dict):
            _push(p.get("route") or "")

    nav = getattr(sources, "navigation", {}) or {}
    for scr in nav.get("screens") or []:
        if not isinstance(scr, dict):
            continue
        data = scr.get("data") if isinstance(scr.get("data"), dict) else {}
        _push(data.get("route") or "")
    return routes


def _derive_route(schema_file: str, sources: Any) -> str:
    """Look up a schema-file's route via nav-flow, else derive from
    filename (``src/schemas/foo/bar.json`` → ``/foo/bar``)."""
    nf = getattr(sources, "nav_flow", {}) or {}
    for p in nf.get("pages") or []:
        if not isinstance(p, dict):
            continue
        sf = p.get("schemaFile") or p.get("schema_path") or ""
        if sf and sf == schema_file:
            r = p.get("route") or ""
            if r:
                return r
    # Filename fallback.
    stem_path = Path(schema_file)
    if stem_path.suffix == ".json":
        parts = stem_path.with_suffix("").parts
        try:
            i = parts.index("schemas")
        except ValueError:
            return ""
        tail = "/".join(parts[i + 1:])
        return "/" + tail if tail else ""
    return ""


# --------------------------------------------------------------------------- #
# Blueprint reference matching
# --------------------------------------------------------------------------- #

def _read_blueprint(root: Path) -> str:
    """Read ``BLUEPRINT.md`` with the ``## Uncovered Artifacts`` section
    stripped out. Without the strip, the coverage check becomes
    unstable: uncovered items get listed inside that section on one
    build, then on the NEXT build appear "referenced" (by their own
    entry in the uncovered list) and drop out — flip-flopping drift on
    every rebuild. Excluding the section itself makes coverage a pure
    function of the OTHER sections' content."""
    p = root / "BLUEPRINT.md"
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    return _strip_uncovered_section(text)


# Very light irregular-plural table; the SQL convention in generated
# apps is almost always +s / +es, so we don't try to be exhaustive.
_IRREGULAR_SINGULARS = {
    "people": "Person", "children": "Child", "men": "Man",
    "women": "Woman", "geese": "Goose", "feet": "Foot",
    "teeth": "Tooth", "mice": "Mouse",
}


def _table_name_variants(sql_name: str) -> list[str]:
    """Return name-forms the blueprint might use to reference this
    SQL table: snake singular, CamelCase plural, CamelCase singular."""
    if not sql_name:
        return []
    out: list[str] = []
    # Snake singular — strip trailing s / es.
    snake_singular = _snake_singularize(sql_name)
    if snake_singular and snake_singular != sql_name:
        out.append(snake_singular)
    # CamelCase both forms.
    camel_plural = _snake_to_camel(sql_name)
    camel_singular = _snake_to_camel(snake_singular) if snake_singular else ""
    for c in (camel_plural, camel_singular):
        if c and c not in out:
            out.append(c)
    return out


def _snake_singularize(name: str) -> str:
    if not name:
        return name
    lower = name.lower()
    if lower in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[lower]
    if lower.endswith("ies"):
        return name[:-3] + "y"
    if lower.endswith("ses") or lower.endswith("xes") or lower.endswith("zes"):
        return name[:-2]
    if lower.endswith("s") and not lower.endswith("ss"):
        return name[:-1]
    return name


def _snake_to_camel(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name or "")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


_UNCOVERED_SECTION_RE = re.compile(
    r"^## Uncovered Artifacts\s*$.*?(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _strip_uncovered_section(text: str) -> str:
    return _UNCOVERED_SECTION_RE.sub("", text or "")


def _is_referenced(
    needle: str, haystack: str, *, extras: list[str] | None = None,
) -> bool:
    """Case-sensitive whole-token match. ``extras`` supplies alternate
    strings that also count as a reference (a page's route or bare
    stem)."""
    if not needle:
        return True  # empty needle: don't flag as uncovered
    if not haystack:
        return False
    if needle in haystack:
        return True
    for e in extras or []:
        if e and e in haystack:
            return True
    return False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _empty_report() -> dict:
    return {
        "covered": 0,
        "uncovered": {
            "pages": [], "tables": [], "workflows": [],
            "entities": [], "routes": [],
        },
        "coverage_pct": 100.0,
    }

"""reorder_column_pass — Spec E Wave 1.

For every entity whose page schemas emit a `Table.reorderable=true`, this
post-gen pass ensures the entity's drizzle schema file carries an
integer `sortOrder` column with a default of 0, and copies the
`/api/data/[entity]/reorder` route template into the generated app.

Flag-gated on ``FORGE_E_INTERACTIONS`` — no-op unless the operator
opts in. Additive + idempotent: safe to re-run.

Design notes
------------
* Entity discovery comes from the page schemas, not the plan JSON. The
  plan may say ``interactions.reorderable`` but the definitive source
  is what the LLM actually shipped in a Table's ``props``; keying off
  the emitted prop keeps the pass honest for hand-authored screens too.
* Table→entity mapping uses the same heuristic as the existing
  ``list_data_source_guard`` (dataSource ``entity`` first, else stem
  match). Kept local so this pass has no cross-guard import surface.
* Drizzle patch is a string splice: insert a new column line just
  before the closing ``});`` of the ``pgTable(...)`` block. Skipped
  when a ``sortOrder`` column is already present (regex tolerant of
  ``sortOrder``/``sort_order``).
* Route template is shipped once at ``src/app/api/data/[...path]/reorder/
  route.ts`` under the catch-all data folder — Next matches deeper
  paths before catch-alls, so this beats the generic route.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_TEMPLATE_ROUTE = Path(__file__).resolve().parents[1] / "templates" / "runtime" / "api-reorder" / "route.ts"

_SORT_COL_RE = re.compile(r"\b(sortOrder|sort_order)\b\s*:", re.IGNORECASE)
_PG_TABLE_END = re.compile(r"^\}\);\s*$", re.MULTILINE)
_PG_TABLE_HEAD = re.compile(r"pgTable\(\s*[\"']([^\"']+)[\"']\s*,\s*\{", re.MULTILINE)


def is_enabled() -> bool:
    """FORGE_E_INTERACTIONS truthy — the spec's opt-in flag."""
    return os.getenv("FORGE_E_INTERACTIONS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _iter_nodes(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v)


def _reorderable_entities(schemas_dir: Path) -> set[str]:
    """Entities whose Table nodes declare `reorderable: true`.

    Falls back to the schema file stem when the Table has no `dataSource`
    binding we can trace to an entity.
    """
    out: set[str] = set()
    if not schemas_dir.exists():
        return out
    for fp in schemas_dir.glob("**/*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        page_entity = None
        for src in (data.get("dataSources") or []):
            if isinstance(src, dict) and src.get("op") in ("list", None) and src.get("entity"):
                page_entity = str(src["entity"])
                break
        for node in _iter_nodes(data):
            if not isinstance(node, dict):
                continue
            if node.get("type") != "Table":
                continue
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            if not props.get("reorderable"):
                continue
            # Prefer an explicit `entity` on the Table's data binding.
            ds = props.get("dataSource")
            ent = None
            if isinstance(ds, dict) and ds.get("entity"):
                ent = str(ds["entity"])
            ent = ent or page_entity or fp.stem
            if ent:
                out.add(ent)
    return out


def _schema_files(schema_dir: Path) -> list[Path]:
    return [p for p in schema_dir.glob("*.ts") if not p.name.startswith("_")]


def _entity_matches_schema_file(entity: str, ts_source: str, filename: str) -> bool:
    """Match either by pgTable name or by the file's exported const name.

    Tolerates simple singular/plural drift (Order↔orders, Category↔categories)
    since the planner keeps entities singular but drizzle tables plural.
    """
    def _norm(s: str) -> str:
        return s.replace("_", "").replace("-", "").lower()

    def _variants(s: str) -> set[str]:
        n = _norm(s)
        out = {n}
        if n.endswith("ies"):
            out.add(n[:-3] + "y")
        elif n.endswith("es") and len(n) > 3:
            out.add(n[:-2])
        if n.endswith("s") and len(n) > 2:
            out.add(n[:-1])
        out.add(n + "s")
        return out

    ent_vars = _variants(entity)
    for name in _PG_TABLE_HEAD.findall(ts_source):
        if _variants(name) & ent_vars:
            return True
    stem = Path(filename).stem
    if _variants(stem) & ent_vars:
        return True
    return False


def _inject_sort_order(ts_source: str) -> tuple[str, bool]:
    """Insert `sortOrder: integer("sort_order").default(0).notNull()` into every
    pgTable body that doesn't already declare it. Returns (new_source, changed)."""
    if _SORT_COL_RE.search(ts_source):
        return ts_source, False

    # Ensure `integer` is imported from drizzle-orm/pg-core.
    changed = False
    new_source = ts_source
    imp_pattern = re.compile(
        r'(import\s*\{\s*)([^}]*?)(\s*\}\s*from\s*[\"\']drizzle-orm/pg-core[\"\'])'
    )
    m = imp_pattern.search(new_source)
    if m and "integer" not in m.group(2):
        replaced_imports = m.group(1) + m.group(2).rstrip().rstrip(",") + ", integer" + m.group(3)
        new_source = new_source[: m.start()] + replaced_imports + new_source[m.end():]
        changed = True

    # Splice a sortOrder line before the closing `});` that terminates the
    # pgTable body. Only patches the FIRST pgTable in the file — schemas
    # emit one entity per file by convention.
    end_match = _PG_TABLE_END.search(new_source)
    if not end_match:
        return ts_source, False
    insertion = '  sortOrder: integer("sort_order").default(0).notNull(),\n'
    new_source = new_source[: end_match.start()] + insertion + new_source[end_match.start():]
    return new_source, True


def _copy_reorder_route(output_root: Path) -> bool:
    """Drop the reorder route.ts into the generated app.

    Placed under `src/app/api/data/[...path]/reorder/route.ts` so it wins
    over the catch-all Data Engine route for that suffix. When the app
    already has a bespoke reorder route we leave it alone.
    """
    if not _TEMPLATE_ROUTE.exists():
        return False
    dst = output_root / "src" / "app" / "api" / "data" / "[...path]" / "reorder" / "route.ts"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.copy2(_TEMPLATE_ROUTE, dst)
    return True


def run(output_dir: str) -> dict[str, Any]:
    """Add sortOrder columns + reorder route where needed. Returns a report."""
    report: dict[str, Any] = {
        "enabled": is_enabled(),
        "entities": [],
        "schema_files_patched": [],
        "route_copied": False,
    }
    if not is_enabled():
        return report

    root = Path(output_dir)
    if not root.exists():
        return report

    schemas_dir = root / "src" / "schemas"
    schema_dir = root / "src" / "db" / "schema"
    entities = _reorderable_entities(schemas_dir)
    report["entities"] = sorted(entities)
    if not entities:
        return report

    if schema_dir.exists():
        for ts_file in _schema_files(schema_dir):
            try:
                src = ts_file.read_text(encoding="utf-8")
            except Exception:
                continue
            hit = any(_entity_matches_schema_file(e, src, ts_file.name) for e in entities)
            if not hit:
                continue
            new_src, changed = _inject_sort_order(src)
            if changed:
                ts_file.write_text(new_src, encoding="utf-8")
                report["schema_files_patched"].append(str(ts_file.relative_to(root)))

    report["route_copied"] = _copy_reorder_route(root)

    if report["schema_files_patched"] or report["route_copied"]:
        logger.info(
            "reorder_column_pass: entities=%s patched=%d route_copied=%s",
            report["entities"], len(report["schema_files_patched"]),
            report["route_copied"],
        )
    return report

"""Binding smoke — assert no binding-backed container ships empty (F2).

The read-binding contract (binding_validator) proves every dataSource
points at a *registered* entity. What it cannot see is whether that
entity will have any DATA on first boot — a Table bound to a perfectly
valid slug still renders an empty shell if the seed plan left the
backing table dry, or if the dataSource's filter excludes every seeded
row. That "structurally correct, visibly broken" class is exactly what
made the reference app's first-paint pages look unfinished.

This pass closes the loop at generation time, statically — no DB, no
app boot. Source of truth is what the shipped seeder itself reads:
``contracts/seed-plan.json`` (per-table ``seed_data`` rows, with the
``sample_data`` bag as fallback — same precedence as seed.ts).

For every page dataSource:
  1. resolve its backing entity (same resolver the binding gate uses),
  2. count seed rows for that entity,
  3. if the dataSource carries simple equality filters, apply them to
     the seed rows — a filter that strips all rows is as empty as no
     rows at all,
  4. check whether the page actually CONSUMES the dataSource (a
     ``{{name}}`` binding anywhere in the tree).

Verdicts:
  - ``empty`` (error)     — consumed dataSource, 0 seed rows survive.
  - ``filtered_empty`` (error) — rows exist but the filter kills them.
  - ``empty_unconsumed`` (info) — dry but nothing renders it.
  - auth-backed entities (users/accounts/sessions) are info, never
    error: they are deliberately unseeded and populate via signup.

FORGE_BINDING_SMOKE=off|warn|strict (default warn, mirroring the
delivery gate: non-binary → read env directly, not flag_profile).
Strict raises BindingSmokeError. Report: contracts/binding-smoke.json.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from services.binding_validator import (
    _canon,
    _read_schema_tables,
    _singularish,
    _SlugResolver,
)
from services.delivery_gate import _load_page_schemas

logger = logging.getLogger(__name__)


def _skey(name: str) -> str:
    """Singular canonical key — seed-plan names entities ("Document")
    while the resolver returns table slugs ("documents"); folding both
    to singular canon is the only join that always holds."""
    return _singularish(_canon(name))


# Deliberately unseeded — populated by auth bootstrap/signup, so an
# empty seed table is expected, not a defect. Singular-canon keys.
_AUTH_CANONS = {"user", "account", "session"}


class BindingSmokeError(RuntimeError):
    """Strict mode: consumed bindings would render empty on first boot."""


def smoke_mode() -> str:
    mode = (os.environ.get("FORGE_BINDING_SMOKE") or "warn").strip().lower()
    return mode if mode in ("off", "warn", "strict") else "warn"


# ── seed-plan reading ───────────────────────────────────────────────

def _seed_rows_by_canon(root: Path) -> dict[str, list[dict]]:
    """canon(entity/table name) → seed rows, using the same precedence
    seed.ts does: per-table ``seed_data`` first, ``sample_data`` bag as
    fallback."""
    path = root / "contracts" / "seed-plan.json"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no seed plan → nothing to assert against
        return {}
    if not isinstance(plan, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for t in plan.get("tables") or []:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            rows = t.get("seed_data")
            out[_skey(t["name"])] = [r for r in rows if isinstance(r, dict)] \
                if isinstance(rows, list) else []
    for name, rows in (plan.get("sample_data") or {}).items():
        c = _skey(name)
        if isinstance(rows, list) and not out.get(c):
            out[c] = [r for r in rows if isinstance(r, dict)]
    return out


# ── dataSource analysis ─────────────────────────────────────────────

def _ds_ref(ds: dict) -> str | None:
    """Same routing the binding gate uses: explicit source keys first,
    name last."""
    for key in ("source", "table", "from", "entity", "name"):
        v = ds.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _eq_filters(ds: dict) -> list[tuple[str, object]]:
    """Extract simple equality conditions; anything richer is skipped
    (we'd rather miss a filter than fake-fail on one we can't model)."""
    out: list[tuple[str, object]] = []
    filters = ds.get("filters")
    if isinstance(filters, list):
        for f in filters:
            if not isinstance(f, dict):
                continue
            op = str(f.get("op") or f.get("operator") or "eq").lower()
            field = f.get("field") or f.get("column")
            if op in ("eq", "=", "equals") and isinstance(field, str) and "value" in f:
                v = f["value"]
                # A binding/param value ({{...}}) is runtime-dependent —
                # not statically checkable.
                if not (isinstance(v, str) and "{{" in v):
                    out.append((field, v))
    where = ds.get("where")
    if isinstance(where, dict):
        for field, v in where.items():
            if isinstance(field, str) and not isinstance(v, (dict, list)) \
                    and not (isinstance(v, str) and "{{" in v):
                out.append((field, v))
    return out


def _rows_surviving(rows: list[dict], filters: list[tuple[str, object]]) -> int:
    if not filters:
        return len(rows)
    n = 0
    for r in rows:
        if all(str(r.get(f)) == str(v) for f, v in filters if f in r):
            n += 1
    return n


def _consumed_names(page: dict) -> set[str]:
    """dataSource names the page actually binds — any ``{{name}}`` or
    ``{{name.…}}`` / ``{{name[0]…}}`` reference in the serialized tree."""
    try:
        blob = json.dumps(page)
    except Exception:  # noqa: BLE001
        return set()
    return {m.group(1) for m in re.finditer(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)", blob)}


# ── the pass ────────────────────────────────────────────────────────

def run_binding_smoke(output_dir: str | Path, *, mode: str | None = None) -> dict:
    root = Path(output_dir)
    mode = mode or smoke_mode()
    findings: list[dict] = []

    if mode != "off":
        seed_rows = _seed_rows_by_canon(root)
        resolver = _SlugResolver(_read_schema_tables(str(root)))

        for route, page in _load_page_schemas(root):
            data_sources = page.get("dataSources")
            if not isinstance(data_sources, list):
                continue
            consumed = _consumed_names(page)
            for ds in data_sources:
                if not isinstance(ds, dict):
                    continue
                ref = _ds_ref(ds)
                if ref is None:
                    continue
                slug = resolver.resolve(ref)
                if slug is None:
                    continue  # binding gate's territory (datasource_unresolved)
                canon = _skey(slug)
                rows = seed_rows.get(canon)
                if rows is None:
                    # Entity registered but absent from the seed plan
                    # entirely — same first-paint outcome as zero rows.
                    rows = []
                filters = _eq_filters(ds)
                surviving = _rows_surviving(rows, filters)
                if surviving > 0:
                    continue

                name = str(ds.get("name") or ref)
                is_consumed = name in consumed
                is_auth = canon in _AUTH_CANONS
                if rows and filters:
                    verdict, detail = "filtered_empty", (
                        f"{len(rows)} seed row(s) exist but filter "
                        f"{filters!r} excludes every one"
                    )
                else:
                    verdict = "empty" if is_consumed else "empty_unconsumed"
                    detail = f"backing entity '{slug}' has no seed rows"
                severity = "info" if (is_auth or not is_consumed) else "error"
                findings.append({
                    "route": route, "dataSource": name, "entity": slug,
                    "verdict": verdict, "severity": severity, "detail": detail,
                    "repair_hint": "seed_synthesizer minimum-target for this "
                                   "entity / relax the dataSource filter",
                })

    errors = [f for f in findings if f["severity"] == "error"]
    report = {
        "mode": mode,
        "summary": {"error": len(errors),
                    "info": len([f for f in findings if f["severity"] == "info"])},
        "findings": findings,
    }
    try:
        out = root / "contracts" / "binding-smoke.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[binding-smoke] could not write report: %s", exc)

    if errors:
        logger.warning("[binding-smoke] %d binding(s) would render empty on "
                       "first boot — see binding-smoke.json", len(errors))
        if mode == "strict":
            lines = "; ".join(f"{f['route']}:{f['dataSource']}" for f in errors[:8])
            raise BindingSmokeError(
                f"{len(errors)} consumed binding(s) have no surviving seed "
                f"rows: {lines}"
            )
    return report


__all__ = ["BindingSmokeError", "run_binding_smoke", "smoke_mode"]

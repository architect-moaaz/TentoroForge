"""V&F 2.0 Layer B — deterministic autofix handlers (Milestone M1).

Five new handlers, each idempotent and safe to re-run. Each takes a
:class:`ClassifiedFault` + the generated app's ``output_dir`` and returns
a :class:`DispatchResult`. Handlers reuse existing seams rather than
reimplementing anything — they exist to route a classified fault to the
right existing service.

Seam mapping:
  - ``deterministic:add-page``          → :func:`services.fix_applier._apply_add_page`
  - ``deterministic:router-regen``      → :func:`services.schema_pipeline._regenerate_route_registry`
  - ``deterministic:db-migrate``        → ``npx drizzle-kit push`` in the generated app
  - ``deterministic:rewire-datasource`` → schema.json patch backed by binding_validator
  - ``deterministic:orphan-wiring``     → :func:`services.orphan_wiring_pass.wire_orphan_workflows`

All handlers catch their own exceptions and return an error-bearing
:class:`DispatchResult` — a single handler's failure never bubbles up
and stops the dispatcher.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from services.journey_verifier.autofix import DispatchResult
from services.journey_verifier.fault_classifier import ClassifiedFault

logger = logging.getLogger(__name__)


# ── add-page (deterministic:add-page) ───────────────────────────────────────


def handle_add_page(fault: ClassifiedFault, output_dir: str | Path) -> DispatchResult:
    """Recreate a missing page by delegating to ``_apply_add_page``.

    Infers the page ``kind`` from the route:
      - ends in ``/new``       → ``create``
      - contains ``/[id]/edit``→ ``edit``
      - contains ``/[id]``     → ``detail``
      - anything else          → ``list``

    Best-effort — the seam handles idempotency: if the schema for the
    route already exists, it patches instead of clobbering.
    """
    try:
        route = fault.route or ""
        kind = _infer_page_kind(route)
        entity = _infer_entity(route)
        diagnosis = {
            "artifact": {"kind": "page", "path": route},
            "explanation": (
                f"V&F autofix: journey verifier saw 404 at `{route}` and the "
                f"route is not in the routes registry."
            ),
            "proposedFix": {
                "seam": "add_page",
                "patch": {
                    "archetype": kind,
                    "entity": entity,
                    "route": route,
                    "title": None,
                    "features": None,
                    "fields": None,
                },
            },
        }
        from services.fix_applier import _apply_add_page

        result = _apply_add_page(str(output_dir), diagnosis, git=False)
        applied = bool(result.get("applied") or result.get("changes"))
        files = [c.get("path") for c in (result.get("changes") or []) if c.get("path")]
        return DispatchResult(
            seam="deterministic:add-page",
            ran=True,
            summary=(
                f"add_page({kind}, {entity or '?'}, {route}) → "
                f"{'applied' if applied else 'noop'}"
            ),
            ok=True,
            class_name=fault.class_name,
            files_touched=list(files),
            fixed=applied,
            smith_turns_used=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("handle_add_page failed for %s: %s", fault.route, exc)
        return _error(fault, "deterministic:add-page", exc)


def _infer_page_kind(route: str) -> str:
    r = (route or "").rstrip("/")
    if r.endswith("/new"):
        return "create"
    if "/[id]/edit" in r or r.endswith("/edit"):
        return "edit"
    if "/[id]" in r or _ends_with_dynamic_seg(r):
        return "detail"
    return "list"


def _ends_with_dynamic_seg(route: str) -> bool:
    """`/foo/[bar]` at end (any bracketed slug)."""
    last = route.rsplit("/", 1)[-1] if "/" in route else route
    return last.startswith("[") and last.endswith("]")


def _infer_entity(route: str) -> str:
    """Best-effort entity slug from the route.

    ``/applicants/new`` → ``applicants``; ``/admin/roles/[id]/edit`` →
    ``roles``. Falls back to empty string if the route is unusable —
    the add_page seam has its own guardrail and will noop.
    """
    if not route:
        return ""
    parts = [p for p in route.split("/") if p and not p.startswith("[")
             and p not in ("new", "edit")]
    return parts[-1] if parts else ""


# ── router-regen (deterministic:router-regen) ───────────────────────────────


def handle_router_regen(fault: ClassifiedFault, output_dir: str | Path) -> DispatchResult:
    """Rewrite ``src/schemas/registry.ts`` so the catch-all route finds
    every schema.json currently on disk.

    Reuses ``schema_pipeline._regenerate_route_registry`` — the same
    helper the pipeline calls after every add_page. Idempotent: rewrites
    the file whether or not it exists.
    """
    try:
        from services.schema_pipeline import _regenerate_route_registry

        _regenerate_route_registry(str(output_dir))
        registry_path = Path(output_dir) / "src" / "schemas" / "registry.ts"
        touched = [str(registry_path)] if registry_path.exists() else []
        return DispatchResult(
            seam="deterministic:router-regen",
            ran=True,
            summary=f"regenerated {registry_path.name}",
            ok=True,
            class_name=fault.class_name,
            files_touched=touched,
            fixed=bool(touched),
            smith_turns_used=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("handle_router_regen failed: %s", exc)
        return _error(fault, "deterministic:router-regen", exc)


# ── db-migrate (deterministic:db-migrate) ───────────────────────────────────


def handle_db_migrate(fault: ClassifiedFault, output_dir: str | Path) -> DispatchResult:
    """Push the drizzle schema against the running database.

    Generated apps use ``drizzle-kit push`` (not alembic — that's for the
    backend platform itself). This is the same command
    ``preview_manager`` runs after a regenerate. If ``DATABASE_URL`` isn't
    set in the environment the handler bails with a clear error rather
    than pushing against the wrong DB.
    """
    try:
        out = Path(output_dir)
        drizzle_config = out / "drizzle.config.ts"
        if not drizzle_config.exists():
            return DispatchResult(
                seam="deterministic:db-migrate",
                ran=True,
                summary="no drizzle.config.ts — skipped",
                ok=True,
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            )
        env = os.environ.copy()
        if not env.get("DATABASE_URL"):
            return DispatchResult(
                seam="deterministic:db-migrate",
                ran=True, ok=False,
                summary="DATABASE_URL unset — refusing to run drizzle push",
                error="DATABASE_URL not set",
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            )
        proc = subprocess.run(
            ["npx", "drizzle-kit", "push"],
            cwd=str(out),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = proc.returncode == 0
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        summary = "drizzle push " + ("ok" if ok else "failed")
        if tail:
            summary += " · " + " / ".join(t[:120] for t in tail)
        return DispatchResult(
            seam="deterministic:db-migrate",
            ran=True,
            ok=ok,
            summary=summary,
            error=None if ok else (proc.stderr or "drizzle push nonzero")[:400],
            class_name=fault.class_name,
            files_touched=[],
            fixed=ok,
            smith_turns_used=0,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("handle_db_migrate timeout: %s", exc)
        return _error(fault, "deterministic:db-migrate", exc,
                      summary="drizzle push timed out")
    except Exception as exc:  # noqa: BLE001
        logger.warning("handle_db_migrate failed: %s", exc)
        return _error(fault, "deterministic:db-migrate", exc)


# ── rewire-datasource (deterministic:rewire-datasource) ─────────────────────


def handle_rewire_datasource(fault: ClassifiedFault, output_dir: str | Path) -> DispatchResult:
    """Repoint an empty list's ``dataSource`` at the entity's canonical slug.

    Uses :func:`services.binding_validator._read_schema_tables` to find
    what tables exist, then rewrites the offending schema.json's Table/
    List ``props.dataSource`` to the entity slug we inferred from the
    route. Idempotent: if the current dataSource already matches, the
    file is untouched.
    """
    try:
        out = Path(output_dir)
        route = fault.route or ""
        entity = _infer_entity(route)
        if not entity:
            return DispatchResult(
                seam="deterministic:rewire-datasource",
                ran=True, ok=True,
                summary=f"could not infer entity from route `{route}` — skipped",
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            )

        # Load table registry to pick the closest slug (entity, plurals,
        # camelCase variants). Fall back to the entity name literally.
        canonical_slug = _find_canonical_slug(out, entity) or entity

        schema_path = _resolve_schema_path(out, route)
        if not schema_path or not schema_path.exists():
            return DispatchResult(
                seam="deterministic:rewire-datasource",
                ran=True, ok=True,
                summary=f"no schema on disk for route `{route}` — skipped",
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            )

        try:
            page = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _error(fault, "deterministic:rewire-datasource", exc,
                          summary=f"could not parse {schema_path.name}")

        changed = _rewrite_datasource(page, canonical_slug)
        if changed:
            schema_path.write_text(
                json.dumps(page, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return DispatchResult(
            seam="deterministic:rewire-datasource",
            ran=True, ok=True,
            summary=(
                f"dataSource → `{canonical_slug}` in {schema_path.name}"
                if changed else
                f"dataSource already `{canonical_slug}` in {schema_path.name}"
            ),
            class_name=fault.class_name,
            files_touched=[str(schema_path)] if changed else [],
            fixed=changed,
            smith_turns_used=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("handle_rewire_datasource failed: %s", exc)
        return _error(fault, "deterministic:rewire-datasource", exc)


def _find_canonical_slug(output_dir: Path, wanted: str) -> str | None:
    """Read the schema tables; pick the drizzle `.arg` (SQL name) whose
    normalized form matches ``wanted``. Never raises."""
    try:
        from services.binding_validator import _read_schema_tables

        tables = _read_schema_tables(str(output_dir))
    except Exception:
        return None
    if not tables:
        return None

    def _norm(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    target = _norm(wanted)
    # Exact then plural-ish
    for t in tables:
        arg = str(t.get("arg") or "")
        if _norm(arg) == target:
            return arg
    for t in tables:
        arg = str(t.get("arg") or "")
        if _norm(arg).rstrip("s") == target.rstrip("s"):
            return arg
    return None


def _resolve_schema_path(output_dir: Path, route: str) -> Path | None:
    """Find src/schemas/**/schema.json for the given route.

    We try the naive path ``src/schemas/<slugified>.json`` first, then
    scan the tree for any file whose plan-emitted route matches. Never
    raises."""
    if not route:
        return None
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return None

    # Cheap heuristic — routes map to slugs by dropping the leading `/`.
    naive = sdir / (route.lstrip("/") + ".json")
    if naive.exists():
        return naive

    # Fall back: scan every schema.json and return the first whose
    # top-level ``route`` field matches.
    for fp in sorted(sdir.rglob("*.json")):
        try:
            page = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(page, dict) and str(page.get("route") or "") == route:
            return fp
    return None


_LIST_KINDS = {"Table", "List", "DataTable", "Kanban", "Calendar", "ResourceTimeline"}


def _rewrite_datasource(page: Any, slug: str) -> bool:
    """Walk the schema tree; on any Table/List-family node whose
    ``props.dataSource`` differs, overwrite it. Returns True if anything
    changed. In-place mutation."""
    changed = False
    stack: list[Any] = [page]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            kind = node.get("type") or node.get("kind") or node.get("component")
            if kind in _LIST_KINDS:
                props = node.setdefault("props", {})
                if isinstance(props, dict):
                    current = props.get("dataSource")
                    if current != slug:
                        props["dataSource"] = slug
                        changed = True
            for v in node.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            for v in node:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return changed


# ── orphan-wiring (deterministic:orphan-wiring) ─────────────────────────────


def handle_orphan_wiring(fault: ClassifiedFault, output_dir: str | Path) -> DispatchResult:
    """Thin adapter over ``orphan_wiring_pass.wire_orphan_workflows``.

    The pass is already idempotent and covers "form submit dispatches
    nothing" cases (its raison d'être). We just call it and report."""
    try:
        from services.orphan_wiring_pass import wire_orphan_workflows

        res = wire_orphan_workflows(str(output_dir))
        # WirePassResult is a TypedDict (== dict at runtime).
        wired = list(res.get("wired") if isinstance(res, dict) else []) or []
        unresolved = list(res.get("unresolved") if isinstance(res, dict) else []) or []
        summary = f"orphan_wiring wired={len(wired)} unresolved={len(unresolved)}"
        return DispatchResult(
            seam="deterministic:orphan-wiring",
            ran=True, ok=True,
            summary=summary,
            class_name=fault.class_name,
            files_touched=[],  # the pass writes but doesn't report file paths
            fixed=bool(wired),
            smith_turns_used=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("handle_orphan_wiring failed: %s", exc)
        return _error(fault, "deterministic:orphan-wiring", exc)


# ── shared error path ──────────────────────────────────────────────────────


def _error(
    fault: ClassifiedFault,
    seam: str,
    exc: BaseException,
    *,
    summary: str | None = None,
) -> DispatchResult:
    return DispatchResult(
        seam=seam,
        ran=True,
        ok=False,
        summary=summary or f"{seam} failed",
        error=str(exc)[:400],
        class_name=fault.class_name,
        files_touched=[],
        fixed=False,
        smith_turns_used=0,
    )

"""Prune per-app API routes + imperative services so the runtime engines are the
single execution path.

Two injected, identical-across-apps runtimes own execution:

  1. **Data Engine** catch-all (`src/app/api/data/[...path]/route.ts`) — the single
     CRUD path (owner-FK defaulting, column filtering, rules validation).
  2. **Workflow engine** (`src/lib/workflows/*` + the standard `/api/workflows/*`
     routes) — the single path for DOMAIN logic. A domain action (approve, reject,
     advance, recalc, notify) is expressed as workflow JSON and triggered through
     the standard workflow API; the frontend WorkflowDispatcher posts to it.

Anything the BusinessLogic agent leaves that bypasses those runtimes is redundant
and, worse, a second source of truth that drifts from the workflow definitions:

  - per-entity CRUD route files (`<entity>/route.ts`, `<entity>/[id]/route.ts`,
    `<entity>/stats/route.ts`, plus the `data/<entity>/…` shadowing variant),
  - per-entity DOMAIN-ACTION route files (`<entity>/[id]/approve/route.ts`,
    `/reject`, `/review`, `/advance`, …) — these hard-code logic that belongs in
    the workflow and skip the engine entirely,
  - imperative TS service files under `src/services/*.ts` that those routes call.

This deletes all three, preserving the catch-all itself, auth, and the standard
workflow infra routes (anything under the reserved `workflows` segment).

Pure-deterministic, idempotent, and safe to run on an already-pruned tree.
"""
from __future__ import annotations

import json
from pathlib import Path

# Top-level api segments that are infrastructure, never entity CRUD.
#
# The runtime-injection manifest is the authoritative source-of-truth for
# what's infra; this set is a safety BELT for two cases:
#   1. Foundation-level segments (auth, next-auth, health, editor) that
#      predate the manifest and don't come from runtime_injector.
#   2. Belt-and-suspenders coverage for injected roots — if the manifest
#      is missing AND its LEGACY fallback misses a case, having the
#      parent segment reserved here still stops _is_domain_action_route /
#      _redundant_crud from mowing the route.
_RESERVED = {
    "auth", "workflows", "health", "cron", "editor", "figma",
    "webhooks", "uploads",
    # Injected-infra parent segments (also covered by the manifest).
    "files", "notifications", "documents", "export",
}

# The manifest runtime_injector writes with every generation. When present,
# every route path listed is skipped by prune regardless of pattern — the
# injector is the single source of truth for what's infra. When absent
# (older apps, or an injection that failed), we fall back to a
# hand-maintained infra list so a stale tree isn't silently mowed by the
# prune pass on its next run.
_INJECTION_MANIFEST_REL = Path("contracts") / "runtime-injection-manifest.json"

# Fallback allowlist for the pre-manifest era. Matches the concrete route
# paths runtime_injector._inject_file_storage / _inject_notifications /
# etc. emit today. Only consulted when the manifest is missing.
_LEGACY_MANIFEST_FALLBACK: frozenset[str] = frozenset({
    "src/app/api/files/upload/route.ts",
    "src/app/api/files/[id]/route.ts",
    "src/app/api/notifications/route.ts",
    "src/app/api/cron/tick/route.ts",
    "src/app/api/documents/pdf/route.ts",
    "src/app/api/export/[entity]/route.ts",
})


def _load_injected_paths(output_dir: Path) -> frozenset[str]:
    """Read the runtime-injection manifest. When missing/broken, fall back
    to a legacy hand-maintained set so an older generated tree isn't
    silently gutted."""
    manifest_path = output_dir / _INJECTION_MANIFEST_REL
    if not manifest_path.is_file():
        return _LEGACY_MANIFEST_FALLBACK
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _LEGACY_MANIFEST_FALLBACK
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, list):
        return _LEGACY_MANIFEST_FALLBACK
    return frozenset(p for p in paths if isinstance(p, str) and p)

# The three CRUD shapes, expressed as the path parts *after* an optional leading
# "data" segment and an entity segment. Each entry is the tuple of remaining parts.
_CRUD_TAILS = {
    ("route.ts",),            # <entity>/route.ts            — collection (list/create)
    ("[id]", "route.ts"),     # <entity>/[id]/route.ts       — item (get/update/delete)
    ("stats", "route.ts"),    # <entity>/stats/route.ts      — count
}


def _is_dynamic(seg: str) -> bool:
    return seg.startswith("[")


def _redundant_crud(parts: tuple[str, ...]) -> bool:
    """True if `parts` (relative to src/app/api/, ending in route.ts) is a
    per-entity CRUD route file that the Data Engine catch-all replaces."""
    if not parts or parts[-1] != "route.ts":
        return False
    p = list(parts)
    # Strip an optional leading "data" segment (the shadowing variant).
    if p[0] == "data":
        p = p[1:]
        if not p:
            return False
        # Never touch the catch-all itself.
        if _is_dynamic(p[0]):
            return False
    if not p:
        return False
    entity = p[0]
    # Entity segment must be a concrete name, not reserved infra or a dynamic seg.
    if entity in _RESERVED or _is_dynamic(entity):
        return False
    return tuple(p[1:]) in _CRUD_TAILS


def _is_domain_action_route(parts: tuple[str, ...]) -> bool:
    """True if `parts` (relative to src/app/api/, ending in route.ts) is a
    per-entity DOMAIN-ACTION route (e.g. `<entity>/[id]/approve/route.ts`).

    These hard-code logic that belongs in a workflow and bypass the engine, so
    under the single-execution-path model they are deleted, not kept. The domain
    action is expressed as workflow JSON and triggered via the standard
    `/api/workflows/...` API instead.

    Reserved infra (`workflows`, `auth`, …), the Data Engine (`data/*`), and
    redundant CRUD (handled by `_redundant_crud`) are excluded here.
    """
    if not parts or parts[-1] != "route.ts":
        return False
    head = parts[0]
    if head in _RESERVED or head == "data" or _is_dynamic(head):
        return False
    # Must live under a concrete entity segment with at least one more segment
    # before route.ts (the action verb, optionally behind `[id]`).
    return len(parts) >= 3 and not _redundant_crud(parts)


def _prune_services(output_dir: Path) -> list[str]:
    """Delete imperative TS domain-logic services under `src/services/*.ts`.

    That directory is exclusively the BusinessLogic agent's output; every file in
    it is imperative domain code that bypasses the workflow engine. The injected
    runtime lives under `src/lib/*`, never here, so clearing it is safe. Returns
    the deleted file names (relative to src/services)."""
    services_root = output_dir / "src" / "services"
    deleted: list[str] = []
    if not services_root.exists():
        return deleted
    for ts_file in sorted(services_root.rglob("*.ts")):
        rel = "/".join(ts_file.relative_to(services_root).parts)
        try:
            ts_file.unlink()
            deleted.append(rel)
        except OSError:
            pass
    return deleted


def prune_entity_crud_routes(output_dir: str | Path) -> dict:
    """Delete per-app artifacts that bypass the injected runtime engines so the
    Data Engine (CRUD) and workflow engine (domain logic) are the single paths.

    Returns {"deleted": [...crud route paths...], "deleted_actions": [...domain
    action route paths...], "deleted_services": [...src/services files...],
    "kept_actions": [], "catch_all": bool}."""
    output_dir = Path(output_dir)
    api_root = output_dir / "src" / "app" / "api"
    result: dict = {
        "deleted": [],
        "deleted_actions": [],
        "deleted_services": [],
        "kept_actions": [],
        "catch_all": False,
    }

    # Imperative TS services are pruned regardless of the api tree's shape.
    result["deleted_services"] = _prune_services(output_dir)

    if not api_root.exists():
        return result

    catch_all = api_root / "data" / "[...path]" / "route.ts"
    result["catch_all"] = catch_all.exists()

    # Manifest-driven skip set: any path runtime_injector persisted to
    # contracts/runtime-injection-manifest.json is treated as infra and
    # never deleted. This replaces the old hand-maintained _RESERVED
    # allowlist for injected routes — a new infra route added to the
    # injector automatically becomes prune-safe without a second edit
    # to this file. `injected_rel` is repo-relative
    # (`src/app/api/...`); we build the same shape from the walk to
    # match against it.
    injected_paths = _load_injected_paths(output_dir)

    for route_file in sorted(api_root.rglob("route.ts")):
        parts = route_file.relative_to(api_root).parts
        rel = "/".join(parts)
        # `.as_posix()`: every entry in the injection manifest — and in
        # `_LEGACY_MANIFEST_FALLBACK` — is a forward-slash literal written by
        # `runtime_injector`'s `append("src/app/api/...")` calls, so `str()`
        # here made the "keep injected infra" escape hatch unreachable on
        # Windows and this pass mowed down the runtime's own API surface
        # (src/app/api/{tasks,cart,events/stream,workflow-runs}/route.ts …)
        # immediately after the injector installed it.
        rel_from_root = route_file.relative_to(output_dir).as_posix()
        # Injected infra route: keep, no matter what pattern matches.
        if rel_from_root in injected_paths:
            continue
        if _redundant_crud(parts):
            try:
                route_file.unlink()
                result["deleted"].append(rel)
            except OSError:
                pass
        elif _is_domain_action_route(parts):
            # A per-entity domain action (approve/reject/review/advance/…) that
            # bypasses the workflow engine. Delete — it belongs in a workflow.
            try:
                route_file.unlink()
                result["deleted_actions"].append(rel)
            except OSError:
                pass

    # Remove directories left empty by the deletions (deepest first).
    for d in sorted(api_root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if d.is_dir():
            try:
                next(d.iterdir())
            except StopIteration:
                d.rmdir()
            except OSError:
                pass

    return result

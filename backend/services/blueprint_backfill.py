"""Backfill Blueprint entries for projects Smith didn't originally
generate through the new pipeline.

Migration Step 5: any project generated before this rewrite has no
`.forge/blueprint.json`. Rather than force the user to re-generate,
we read whatever's on disk (registry, schemas, workflows) and
produce a best-effort initial blueprint. Smith's future turns then
fill in `why` fields and detail as changes land.

Idempotent by default: re-running skips projects that already have
a blueprint. Pass ``force=True`` to overwrite (destructive)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.smith_blueprint import Blueprint, BlueprintPath


logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    project_id: str
    created: bool
    reason: str = ""
    entities: int = 0
    workflows: int = 0
    pages: int = 0
    skipped_fields: list[str] = field(default_factory=list)


@dataclass
class ReconcileResult:
    """Outcome of ``reconcile_blueprint_with_registry``."""
    project_id: str
    reconciled: bool
    reason: str = ""
    entities_added: int = 0
    workflows_added: int = 0
    pages_added: int = 0
    entities_orphaned: list[str] = field(default_factory=list)
    workflows_orphaned: list[str] = field(default_factory=list)
    pages_orphaned: list[str] = field(default_factory=list)


def backfill_project_blueprint(
    *, project_id: str, output_dir: str, force: bool = False,
) -> BackfillResult:
    """Create a `.forge/blueprint.json` for `output_dir` from the
    project's existing registry + schemas + workflows.

    Returns a `BackfillResult` describing what happened; callers
    (typically the migration script) use it for reporting."""
    bp_path = BlueprintPath(output_dir).file
    if bp_path.exists() and not force:
        return BackfillResult(
            project_id=project_id, created=False,
            reason="blueprint already exists",
        )

    registry_path = Path(output_dir) / "contracts" / "resource-registry.json"
    if not registry_path.exists():
        return BackfillResult(
            project_id=project_id, created=False,
            reason=f"registry not found at {registry_path}",
        )

    try:
        registry: dict[str, Any] = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return BackfillResult(
            project_id=project_id, created=False,
            reason=f"registry unreadable: {exc!r}",
        )

    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
    # If force=True and a blueprint exists, wipe the sections we're
    # about to rewrite; keep _extras so a hand-added field survives.
    if force:
        bp.entities.clear()
        bp.workflows.clear()
        bp.pages.clear()

    # Entities — read name/table; skip anything nameless.
    for e in registry.get("entities") or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        columns = e.get("columns") or []
        key_fields = [
            str(c.get("name")) for c in columns
            if isinstance(c, dict) and c.get("name")
        ][:8]
        bp.add_entity(
            name=str(e["name"]),
            table=str(e.get("table") or ""),
            purpose="(backfilled from registry; Smith to fill on next touch)",
            key_fields=key_fields,
            why_shaped_this_way="(pre-blueprint; original rationale unknown)",
        )

    # Workflows — the registry has minimal detail; the file body has
    # more but we don't parse it here. Only the name/id survives.
    for w in registry.get("workflows") or []:
        if not isinstance(w, dict):
            continue
        name = str(w.get("name") or w.get("id") or "").strip()
        if not name:
            continue
        bp.add_workflow(
            name=name,
            purpose="(backfilled from registry)",
            trigger=_trigger_str(w.get("trigger")),
            why="(pre-blueprint; original rationale unknown)",
        )

    # Pages — same story.
    for p in registry.get("pages") or []:
        if not isinstance(p, dict) or not p.get("route"):
            continue
        bp.add_page(
            route=str(p["route"]),
            schema_path=str(p.get("schema_path") or ""),
            role="(backfilled from registry)",
            notable_choices=[],
        )

    bp.append_change_log(
        at=_now_iso(),
        user_ask="",
        smith_move="backfill: reconstructed initial blueprint from registry",
        diff_summary=(
            f"seeded {len(bp.entities)} entities, "
            f"{len(bp.workflows)} workflows, "
            f"{len(bp.pages)} pages"
        ),
        verified_by=["registry.json read"],
        why="pre-blueprint project — Smith will fill detail on next turn",
        source="external",
    )
    bp.save()

    return BackfillResult(
        project_id=project_id, created=True,
        entities=len(bp.entities),
        workflows=len(bp.workflows),
        pages=len(bp.pages),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _trigger_str(t: Any) -> str:
    """Coerce a plan/registry ``trigger`` field to a string.
    Planner + registry both emit str OR {"type": str} inconsistently."""
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return str(t.get("type") or "")
    return ""


# --------------------------------------------------------------------------- #
# Reconcile — keep the Blueprint honest against the app-registry.
#
# Backfill fires on first sight. Reconciliation fires after every build
# (Phase A generation-complete hook) and can be triggered manually.
# The invariant it maintains: what Smith THINKS is in the app matches
# what's ACTUALLY in the app.
#
# It's additive: entities/pages/workflows the registry shows that
# aren't in the Blueprint get added. Items the Blueprint has that the
# registry doesn't get logged as "orphaned" (not deleted — Smith may
# still have context about them, and delete-on-drift is destructive).
# --------------------------------------------------------------------------- #

def reconcile_blueprint_with_registry(
    *, project_id: str, output_dir: str,
) -> ReconcileResult:
    """Merge the app-registry state into an existing Blueprint.

    Non-destructive: adds items the registry has but the Blueprint
    doesn't, and reports items the Blueprint has that the registry
    doesn't (orphans — may indicate deletion drift the user should
    know about). Never removes anything on its own.

    Idempotent: running twice with no registry change is a no-op."""
    bp_path = BlueprintPath(output_dir).file
    registry_path = Path(output_dir) / "contracts" / "resource-registry.json"

    if not registry_path.exists():
        return ReconcileResult(
            project_id=project_id, reconciled=False,
            reason=f"registry not found at {registry_path}",
        )

    try:
        registry: dict[str, Any] = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ReconcileResult(
            project_id=project_id, reconciled=False,
            reason=f"registry unreadable: {exc!r}",
        )

    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)

    existing_entity_names = {e.get("name") for e in bp.entities}
    existing_workflow_names = {w.get("name") for w in bp.workflows}
    existing_page_routes = {p.get("route") for p in bp.pages}

    registry_entity_names: set[str] = set()
    registry_workflow_names: set[str] = set()
    registry_page_routes: set[str] = set()

    entities_added = 0
    for e in registry.get("entities") or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        name = str(e["name"])
        registry_entity_names.add(name)
        if name in existing_entity_names:
            continue
        columns = e.get("columns") or []
        key_fields = [
            str(c.get("name")) for c in columns
            if isinstance(c, dict) and c.get("name")
        ][:8]
        bp.add_entity(
            name=name,
            table=str(e.get("table") or ""),
            purpose="(reconciled from build — registry had it, Blueprint didn't)",
            key_fields=key_fields,
            why_shaped_this_way=(
                "post-generate reconciliation; original rationale unknown"
            ),
        )
        entities_added += 1

    workflows_added = 0
    for w in registry.get("workflows") or []:
        if not isinstance(w, dict):
            continue
        name = str(w.get("name") or w.get("id") or "").strip()
        if not name:
            continue
        registry_workflow_names.add(name)
        if name in existing_workflow_names:
            continue
        bp.add_workflow(
            name=name,
            purpose="(reconciled from build)",
            trigger=_trigger_str(w.get("trigger")),
            why="post-generate reconciliation",
        )
        workflows_added += 1

    pages_added = 0
    for p in registry.get("pages") or []:
        if not isinstance(p, dict) or not p.get("route"):
            continue
        route = str(p["route"])
        registry_page_routes.add(route)
        if route in existing_page_routes:
            continue
        bp.add_page(
            route=route,
            schema_path=str(p.get("schema_path") or ""),
            role="(reconciled from build)",
            notable_choices=[],
        )
        pages_added += 1

    # Orphans: Blueprint has it, registry doesn't. Log them but keep
    # the Blueprint entries — Smith should surface these to the user
    # rather than silently disappearing them.
    entity_orphans = sorted(
        n for n in existing_entity_names
        if n and n not in registry_entity_names
    )
    workflow_orphans = sorted(
        n for n in existing_workflow_names
        if n and n not in registry_workflow_names
    )
    page_orphans = sorted(
        r for r in existing_page_routes
        if r and r not in registry_page_routes
    )

    net_change = entities_added + workflows_added + pages_added
    has_orphans = bool(entity_orphans or workflow_orphans or page_orphans)
    if net_change == 0 and not has_orphans:
        # Nothing to record — Blueprint already agrees with registry.
        return ReconcileResult(
            project_id=project_id, reconciled=True,
            reason="already in sync",
        )

    diff_bits = []
    if entities_added:  diff_bits.append(f"+{entities_added} entities")
    if workflows_added: diff_bits.append(f"+{workflows_added} workflows")
    if pages_added:     diff_bits.append(f"+{pages_added} pages")
    if entity_orphans:  diff_bits.append(f"{len(entity_orphans)} orphan entities")
    if workflow_orphans:diff_bits.append(f"{len(workflow_orphans)} orphan workflows")
    if page_orphans:    diff_bits.append(f"{len(page_orphans)} orphan pages")

    bp.append_change_log(
        at=_now_iso(),
        user_ask="",
        smith_move="reconcile: Blueprint ↔ app-registry",
        diff_summary="; ".join(diff_bits),
        verified_by=["contracts/resource-registry.json read"],
        why=(
            "keep Smith's memory honest against what the pipeline "
            "actually produced (post-generate hook)"
        ),
        source="external" if not net_change else "smith",
    )
    bp.save()

    return ReconcileResult(
        project_id=project_id, reconciled=True,
        entities_added=entities_added,
        workflows_added=workflows_added,
        pages_added=pages_added,
        entities_orphaned=entity_orphans,
        workflows_orphaned=workflow_orphans,
        pages_orphaned=page_orphans,
    )

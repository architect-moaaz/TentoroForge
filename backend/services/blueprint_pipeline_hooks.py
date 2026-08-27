"""Blueprint pipeline hooks — spec §6.3.

Called from the generation pipeline (discovery / planner / generator
stages) so the Blueprint gets populated at authorship time, not
inferred later from a registry snapshot. This is what makes the
"Smith authored this app" claim literal instead of aspirational.

Every hook wraps its work in try/except so that a Blueprint write
failure NEVER breaks generation. Generation is the load-bearing path;
the Blueprint is Smith's memory of it. Losing memory is worse than
losing the app, but a corrupted app is worse than a stale memory.

Public entry points (safe to call from anywhere in the pipeline):

  * :func:`record_discovery` — after the discovery brief is extracted
    from the streaming agent, before user approval.
  * :func:`record_plan` — after the planner produces a normalized
    plan dict, before or after user approval.
  * :func:`record_generation_complete` — one call at the end of a
    full generation run naming the file set.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from services.smith_blueprint import Blueprint


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Discovery hook
# --------------------------------------------------------------------------- #

def record_discovery(
    *, output_dir: str, project_id: str, dossier: dict[str, Any],
) -> None:
    """Set the Blueprint's ``domain`` from a discovery brief.

    Accepts the raw dossier dict (from ``discovery-brief`` extraction).
    Fields consumed: ``domain_name``, ``actors``, ``verbs``,
    ``distinctive_shape``, ``user_prompt`` (optional), ``open_questions``
    (optional — recorded as pending design_decisions).
    """
    try:
        name = str((dossier or {}).get("domain_name") or "").strip()
        if not name:
            logger.info(
                "blueprint_pipeline_hooks.record_discovery: no domain_name; skipping"
            )
            return

        bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
        bp.set_domain(
            name=name,
            primary_actors=[str(a) for a in (dossier.get("actors") or [])],
            core_verbs=[str(v) for v in (dossier.get("verbs") or [])],
            distinctive_shape=str(dossier.get("distinctive_shape") or ""),
            why=str(dossier.get("user_prompt") or "").strip()
                or "recorded during discovery",
        )

        for q in (dossier.get("open_questions") or []):
            if isinstance(q, str) and q.strip():
                bp.add_design_decision(
                    topic="pending: discovery open question",
                    choice=q.strip(),
                    why="raised during discovery; awaiting resolution",
                    authored_at=_now_iso(),
                )

        bp.append_change_log(
            at=_now_iso(),
            user_ask=str(dossier.get("user_prompt") or ""),
            smith_move="discovery: set domain + captured open questions",
            diff_summary=f"domain={name!r} · actors={len(bp.domain['primary_actors'])} · verbs={len(bp.domain['core_verbs'])}",
            verified_by=["discovery-brief extraction"],
            why="foundational — every later move references this",
            source="smith",
        )
        bp.save()
    except Exception:  # noqa: BLE001 — generation must never crash on blueprint write
        logger.exception("blueprint_pipeline_hooks.record_discovery failed")


# --------------------------------------------------------------------------- #
# Planner hook
# --------------------------------------------------------------------------- #

def record_plan(
    *, output_dir: str, project_id: str, plan: dict[str, Any],
) -> None:
    """Populate ``entities`` / ``workflows`` / ``pages`` from a plan
    dict (shape produced by ``agents/planner.py::run_planner_oneshot``).

    Idempotent per (kind, name): calling twice with the same entity
    updates in place rather than duplicating."""
    try:
        if not isinstance(plan, dict):
            return
        bp = Blueprint.load(project_id=project_id, output_dir=output_dir)

        # Support all three plan shapes the pipeline uses:
        #   • `models` (legacy — never actually emitted by run_planner_oneshot;
        #     kept for callers upstream that used to name it this way)
        #   • `data_models` (LIST — pre-normalize form the LLM emits)
        #   • `entities` (DICT `{Name: {...}}` — post `_ensure_normalized_plan`
        #     canonical form). This was silently missed before, which is why
        #     blueprint.json historically showed `entities=0` for every run.
        entities_iter: list[dict] = []
        for src_key in ("models", "data_models"):
            src = plan.get(src_key)
            if isinstance(src, list):
                entities_iter.extend(x for x in src if isinstance(x, dict) and x.get("name"))
        ent_dict = plan.get("entities")
        if isinstance(ent_dict, dict):
            for _name, _e in ent_dict.items():
                if isinstance(_e, dict):
                    entities_iter.append({**_e, "name": _e.get("name") or _name})

        added_entities = 0
        for m in entities_iter:
            if not isinstance(m, dict) or not m.get("name"):
                continue
            name = str(m["name"])
            if any(e.get("name") == name for e in bp.entities):
                continue  # idempotent
            fields = m.get("fields") or []
            key_fields = [
                str(f.get("name")) for f in fields
                if isinstance(f, dict) and f.get("name")
            ][:8]
            bp.add_entity(
                name=name,
                table=str(m.get("table") or ""),
                purpose=str(m.get("purpose") or m.get("description") or "").strip()
                        or "authored during planning",
                key_fields=key_fields,
                why_shaped_this_way=str(m.get("why") or "").strip()
                                    or "planner shaped from user requirement",
            )
            added_entities += 1

        added_workflows = 0
        for w in (plan.get("workflows") or []):
            if not isinstance(w, dict) or not w.get("name"):
                continue
            name = str(w["name"])
            if any(x.get("name") == name for x in bp.workflows):
                continue
            bp.add_workflow(
                name=name,
                purpose=str(w.get("purpose") or w.get("description") or "").strip()
                        or "authored during planning",
                trigger=_trigger_str(w.get("trigger")),
                why=str(w.get("why") or "").strip()
                    or "planner shaped from user requirement",
            )
            added_workflows += 1

        added_pages = 0
        for p in (plan.get("pages") or []):
            if not isinstance(p, dict) or not p.get("route"):
                continue
            route = str(p["route"])
            if any(x.get("route") == route for x in bp.pages):
                continue
            bp.add_page(
                route=route,
                schema_path=str(p.get("schema_path") or ""),
                role=str(p.get("role") or p.get("type") or "").strip()
                     or "authored during planning",
                notable_choices=[],
            )
            added_pages += 1

        if added_entities + added_workflows + added_pages == 0:
            # Nothing new — don't append a noisy change_log entry.
            return

        bp.append_change_log(
            at=_now_iso(),
            user_ask="",
            smith_move=(
                f"planner: +{added_entities} entities · "
                f"+{added_workflows} workflows · +{added_pages} pages"
            ),
            diff_summary=(
                f"entities={len(bp.entities)}, workflows={len(bp.workflows)}, "
                f"pages={len(bp.pages)}"
            ),
            verified_by=["planner artifact"],
            why="plan finalized (may still change on revise)",
            source="smith",
        )
        bp.save()
    except Exception:  # noqa: BLE001
        logger.exception("blueprint_pipeline_hooks.record_plan failed")


# --------------------------------------------------------------------------- #
# Generation-complete hook
# --------------------------------------------------------------------------- #

_FILE_PREVIEW_CAP = 5


def record_generation_complete(
    *, output_dir: str, project_id: str,
    files: list[str], user_ask: str,
) -> None:
    """One change_log entry per generation run naming what shipped.

    Deliberately compact — Smith reads the change_log every turn and
    a full file dump would blow the context budget on large apps."""
    try:
        files = list(files or [])
        preview = ", ".join(f"`{p}`" for p in files[:_FILE_PREVIEW_CAP])
        more = f", +{len(files) - _FILE_PREVIEW_CAP} more" if len(files) > _FILE_PREVIEW_CAP else ""
        summary = f"{len(files)} file(s) generated" + (f": {preview}{more}" if files else "")

        bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
        bp.append_change_log(
            at=_now_iso(),
            user_ask=str(user_ask or ""),
            smith_move="generation: full pipeline run",
            diff_summary=summary,
            verified_by=["post_generate_fixes suite", "atomic commit"],
            why="app materialization for the current plan",
            source="smith",
        )
        bp.save()

        # Reconcile — the plan Smith authored is aspirational; the app
        # on disk is what actually shipped. Merge registry into Blueprint
        # so Smith's memory matches what he actually built (idempotent;
        # safe on first-ever build). Never blocks the pipeline.
        try:
            from services.blueprint_backfill import reconcile_blueprint_with_registry
            reconcile_blueprint_with_registry(
                project_id=project_id, output_dir=output_dir,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "blueprint_pipeline_hooks: post-generate reconcile failed",
            )
    except Exception:  # noqa: BLE001
        logger.exception("blueprint_pipeline_hooks.record_generation_complete failed")


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _trigger_str(t: Any) -> str:
    """Coerce a plan ``trigger`` field to a string.
    Planner emits str OR {"type": str} inconsistently."""
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return str(t.get("type") or "")
    return ""

"""Post-generation housekeeping.

Code *quality* is the responsibility of the LLM agents. This module handles two
narrow, deterministic concerns that aren't code-quality:
- Clearing stale build cache so the validator gets a clean environment.
- DB-schema integrity that, if wrong, hard-fails the migration (not a style
  issue): FK column types must match the PK they reference, or Postgres refuses
  the constraint and seeding inserts 0 rows. See services/fk_type_guard.py.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def apply_post_generate_fixes_with_result(output_dir: str, *, force: bool = False):
    """Run the full guard suite and return a structured :class:`GuardResult`
    for callers (Smith orchestrator, tests) that need a machine-readable
    pass/fail verdict.

    Wraps :func:`apply_post_generate_fixes` in a scoped log capture so
    every WARNING / ERROR the guards emit becomes a
    :class:`GuardFailure` entry — no guard code needed to change.
    Backwards-compat: the underlying function still writes files + logs
    exactly as before; the ``int`` return of the classic API is
    unchanged.
    """
    from services.guard_result import GuardResult, capture_guard_logs

    # S22-2: snapshot the workflows BEFORE the guards run.
    #
    # The suite reported only what guards happened to log, so a guard that
    # rewrote authored workflow content reported nothing — and Smith is pushed
    # to run this pass immediately after an edit, which is exactly when a
    # silent rewrite is indistinguishable from the edit never having saved.
    #
    # Diffing the files is deliberate rather than adding a log line to each
    # guard: it covers ~20 existing guards and every one added later without
    # any of them having to remember.
    before = _snapshot_workflows(output_dir)

    with capture_guard_logs() as records:
        try:
            apply_post_generate_fixes(output_dir, force=force)
        except Exception as exc:  # noqa: BLE001 — surface as a failure, don't crash caller
            logger.exception("[guard-suite] crashed during run: %r", exc)
            records.append({
                "name": "services.post_generate_fixes",
                "level": "error",
                "message": f"guard suite crashed: {exc!r}",
            })

    result = GuardResult.from_log_records(records)
    result.rewrites = _diff_workflows(before, _snapshot_workflows(output_dir))
    for wf_name, changes in result.rewrites.items():
        for c in changes:
            logger.warning(
                "[guard-suite] rewrote %s at %s: %r -> %r",
                wf_name, c["path"], c["before"], c["after"],
            )
    return result


# --------------------------------------------------------------------------- #
# Rewrite reporting (S22-2)
# --------------------------------------------------------------------------- #

def _snapshot_workflows(output_dir: str) -> dict[str, Any]:
    """Every workflow JSON under ``output_dir``, parsed, keyed by relative path.

    Unreadable or malformed files are skipped rather than raised: this is
    observability, and it must never be the thing that fails a guard run.
    """
    import json as _json

    root = Path(output_dir)
    out: dict[str, Any] = {}
    if not root.exists():
        return out
    for path in root.rglob("*.json"):
        if "workflow" not in str(path.parent).lower() and "workflow" not in path.stem.lower():
            continue
        if "node_modules" in path.parts:
            continue
        try:
            out[str(path.relative_to(root))] = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a malformed file is not our error to raise
            continue
    return out


def _diff_workflows(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Leaf-level changes between two workflow snapshots.

    Reports the dotted path plus the old and new value, so the caller can say
    WHAT was changed rather than merely that something was. A removed key is
    reported with ``after: None``, which is the case that matters most — that
    is authored content disappearing.
    """
    changes: dict[str, list[dict[str, Any]]] = {}

    def walk(a: Any, b: Any, path: str, acc: list[dict[str, Any]]) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), f"{path}.{key}" if path else str(key), acc)
            return
        if isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                walk(
                    a[i] if i < len(a) else None,
                    b[i] if i < len(b) else None,
                    f"{path}[{i}]", acc,
                )
            return
        if a != b:
            acc.append({"path": path, "before": a, "after": b})

    for name, old_doc in before.items():
        acc: list[dict[str, Any]] = []
        walk(old_doc, after.get(name), "", acc)
        if acc:
            changes[name] = acc
    for name in after.keys() - before.keys():
        changes[name] = [{"path": "", "before": None, "after": "<new file>"}]
    return changes


def apply_post_generate_fixes(output_dir: str, *, force: bool = False) -> int:
    """Run deterministic post-gen fixes. Returns the number of fixes applied.

    Phase 7 — idempotency guard: if the suite has already completed for
    ``output_dir`` in this process, log a warning and no-op. Smith edit
    flows that legitimately need a re-run pass ``force=True``. The tail
    of the suite marks the run complete; ``reset_run`` at the top clears
    the per-run guard counter so we always start from a clean slate.
    """
    from services.post_gen_phases import (
        is_run_complete,
        mark_run_complete,
        reset_run,
    )

    root = Path(output_dir)
    if not root.exists():
        return 0

    if is_run_complete(output_dir) and not force:
        logger.warning(
            "[post-gen] apply_post_generate_fixes called twice for %s in the "
            "same process — skipping the second call. Pass force=True if this "
            "is a Smith re-apply after an edit.",
            output_dir,
        )
        return 0

    reset_run(output_dir)
    applied = 0

    # Schema JSON repair — MUST run first. The refiner edits schema .json files with
    # string splices that can leave a trailing comma (valid JS, invalid JSON); Next
    # imports these as JSON, so one stray comma crashes the whole build. Repair before
    # any later guard tries to parse a schema (and choke on the malformed one).
    try:
        from services.schema_json_repair import repair_schema_json
        jr = repair_schema_json(str(root))
        if jr["repaired"]:
            logger.info("schema_json_repair: fixed %d malformed schema file(s) in %s: %s",
                        len(jr["repaired"]), root, ", ".join(jr["repaired"]))
            applied += len(jr["repaired"])
        if jr["unfixable"]:
            logger.error("schema_json_repair: %d schema file(s) still invalid in %s: %s",
                         len(jr["unfixable"]), root, ", ".join(jr["unfixable"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_json_repair failed: %s", e)

    # DB-integrity: a table name declared by TWO schema files (e.g. template auth
    # `user.ts` with a `password` column AND a plan-derived `users.ts` without one)
    # is fatal — drizzle globs the whole schema dir, the wrong definition can win
    # the migration, and seed dies with `column "password" of relation "users"
    # does not exist`. Keep the canonical (auth/most-complete) file, delete the
    # redundant one(s), and clean the barrel. Runs early, right after the JSON
    # repair, so no later schema guard operates on a doomed duplicate set.
    try:
        from services.schema_dedup_guard import dedup_schema_tables
        dd = dedup_schema_tables(str(root))
        if dd.get("duplicates"):
            applied += len(dd["removed"])
            logger.warning(
                "schema_dedup_guard: resolved %d duplicate pgTable(s) in %s — removed %s%s",
                len(dd["duplicates"]), output_dir,
                ", ".join(Path(f).name for f in dd["removed"]) or "(none)",
                f"; UNRESOLVED {', '.join(Path(f).name for f in dd['unresolved'])}"
                if dd.get("unresolved") else "",
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("schema_dedup_guard failed: %s", e)

    # BUILD-integrity: reconcile the dynamic `import("@/db/schema/<X>")` lines in
    # src/lib/data-init.ts and src/app/api/data/[...path]/route.ts to the schema
    # files that ACTUALLY survive. runtime_injector globs the schema dir to emit
    # those imports BEFORE dedup (above) deletes plural/duplicate files, so they can
    # reference a now-deleted module (`@/db/schema/customers`). Promise.allSettled
    # tolerates it at runtime, but webpack fails the BUILD (`Module not found: Can't
    # resolve '@/db/schema/customers'`). MUST run AFTER dedup so the surviving set
    # is settled. Additive + idempotent.
    try:
        from services.schema_import_guard import reconcile_schema_imports
        si = reconcile_schema_imports(str(root))
        if si.get("removed") or si.get("added"):
            applied += si["removed"] + si["added"]
            logger.info(
                "schema_import_guard: pruned %d dead + added %d missing schema import(s) "
                "across %d file(s) in %s",
                si["removed"], si["added"], si["files_changed"], output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("schema_import_guard failed: %s", e)

    # DB-integrity: a workflow db_* node whose `config.table` doesn't match a real
    # `pgTable("X")` throws `unknown table` at RUNTIME for the user. The usual cause
    # is casing drift (planner snake_case `knowledge_articles` vs schema camelCase
    # `knowledgeArticles`) — the SAME table. Runs AFTER dedup so the schema is
    # settled first, then auto-heals every reconcilable name and loudly flags any
    # genuinely-missing table it cannot reconcile.
    # TG-1: set inside the try when the operator's strict gate trips, re-raised
    # after the handlers. Declared here so the broad `except Exception` below
    # cannot swallow a deliberate gate failure.
    table_gate_failure: RuntimeError | None = None
    try:
        from services.schema_tables import SchemaNotFoundError
        from services.workflow_table_guard import reconcile_workflow_tables
        wt = reconcile_workflow_tables(str(root))
        if wt.get("remapped") or wt.get("unresolved"):
            applied += len(wt["remapped"])
            logger.warning(
                "workflow_table_guard: scanned %d workflow(s) in %s — remapped %d "
                "(%s); UNRESOLVED %d%s",
                wt["files_scanned"], output_dir, len(wt["remapped"]),
                ", ".join(f"{f}:{a}->{b}" for f, a, b in wt["remapped"]) or "(none)",
                len(wt["unresolved"]),
                f" ({', '.join(f'{f}:{t}' for f, t in wt['unresolved'])})"
                if wt["unresolved"] else "",
            )
        # TG-1 — optional enforcement, off by default.
        #
        # The guard now reports unresolved tables loudly, but generation still
        # continues, so a workflow KNOWN to reference a missing table can still
        # ship. Whether that should fail the build is a product call, so it is
        # opt-in on the same env-flag precedent as FORGE_BINDING_GATE=strict.
        if wt.get("unresolved") and os.environ.get("FORGE_TABLE_GATE") == "strict":
            # TG-1: this `raise` used to sit inside the try whose handler below is
            # a broad `except Exception`, so the gate CAUGHT ITS OWN ENFORCEMENT —
            # the run logged "workflow_table_guard failed: FORGE_TABLE_GATE=strict:
            # ..." at ERROR and then returned normally. The advertised escape
            # hatch did nothing: the same class of unmet guarantee TG-1 was
            # raised for, moved one level down.
            table_gate_failure = RuntimeError(
                "FORGE_TABLE_GATE=strict: "
                f"{len(wt['unresolved'])} workflow table(s) do not exist in the "
                f"schema and would fail at runtime: "
                + ", ".join(f"{f}:{t}" for f, t in wt["unresolved"])
            )
    except SchemaNotFoundError as e:
        # The guard could not find a schema to check workflows against, so it
        # verified NOTHING. Reporting this at warning level next to ordinary
        # skips is what let TG-2 hide: the run looked clean because the check
        # never happened. It is a broken tree, not a soft skip.
        logger.error(
            "workflow_table_guard: NOT RUN — %s. Every workflow table in %s is "
            "unverified; `unknown table` failures will surface at runtime.",
            e, output_dir,
        )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.exception("workflow_table_guard failed: %s", e)

    # TG-1: raised OUTSIDE the try. "never block generation on the guard" is the
    # right default for a guard that crashed unexpectedly; it is the wrong rule
    # for an operator who explicitly asked to be blocked.
    if table_gate_failure is not None:
        raise table_gate_failure

    # Mutation executability: a button/manual-triggered db_update/db_insert whose
    # `values` are self-referential (`{"status":"{{status}}"}`) with no trigger input
    # backing them resolves to NULL at runtime and WIPES the column — so "Confirm
    # Pickup"/"Process Return"/"Cancel" appear to do nothing. Heal each such value to
    # a real literal: status ← the node label ("Set Picked Up" → "Picked Up"), a
    # lifecycle *At ← CURRENT_TIMESTAMP. Runs right after the table guard so the
    # workflow shape is settled. Deterministic, idempotent, never raises.
    try:
        from services.workflow_mutation_guard import heal_workflow_mutations
        mg = heal_workflow_mutations(str(root))
        if mg.get("values_healed"):
            applied += mg["values_healed"]
            logger.info(
                "workflow_mutation_guard: healed %d mutation value(s) across %d workflow(s) "
                "in %s (%d left needing an input)",
                mg["values_healed"], mg["workflows_scanned"], output_dir, mg["unresolved"],
            )
        elif mg.get("unresolved"):
            logger.warning(
                "workflow_mutation_guard: %d mutation value(s) still need a trigger input in %s",
                mg["unresolved"], output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("workflow_mutation_guard failed: %s", e)

    try:
        from services.list_data_source_guard import reconcile_list_sources
        ls = reconcile_list_sources(str(root))
        _ls_fixes = len(ls.get("binding_remapped", [])) + len(ls.get("source_remapped", []))
        if _ls_fixes:
            applied += _ls_fixes
            logger.info(
                "list_data_source_guard: remapped %d binding(s) + %d source(s) across %d file(s) in %s",
                len(ls["binding_remapped"]), len(ls["source_remapped"]),
                ls.get("files_changed", 0), output_dir,
            )
        if ls.get("binding_unresolved") or ls.get("source_unresolved"):
            logger.warning(
                "list_data_source_guard: UNRESOLVED %d binding(s), %d source(s) in %s",
                len(ls.get("binding_unresolved", [])),
                len(ls.get("source_unresolved", [])), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("list_data_source_guard failed: %s", e)

    # CRUD invariant: every LIST page over a registered entity MUST have
    # a header button navigating to that entity's /new route. LLM-authored
    # list pages routinely drop the button; button_audit can only heal
    # EXISTING buttons — it can't invent one. This pass invents when
    # missing. Runs after list_data_source_guard so the slug set is
    # settled and idempotent — a re-run on a fixed page is a no-op.
    try:
        from services.crud_invariants import (
            ensure_list_pages_have_create_action,
        )
        ci = ensure_list_pages_have_create_action(output_dir)
        if ci.inserted:
            applied += len(ci.inserted)
            logger.info(
                "crud_invariants: inserted %d 'New X' button(s) across %d file(s) in %s",
                len(ci.inserted), ci.files_changed, output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("crud_invariants failed: %s", e)

    # ACTION invariant (Slice B): every planner-declared page.actions[]
    # target must land in the schema as a Button. The deterministic
    # detail-page builder already consumes page.actions — but any
    # LLM-authored detail page won't. This pass inserts declared action
    # buttons that are missing. Runs after crud_invariants so the two
    # invariants can share a header actions row.
    try:
        from services.action_invariants import (
            ensure_declared_actions_present,
        )
        ai = ensure_declared_actions_present(output_dir)
        if ai.inserted:
            applied += len(ai.inserted)
            logger.info(
                "action_invariants: inserted %d declared action button(s) across %d file(s) in %s",
                len(ai.inserted), ai.files_changed, output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("action_invariants failed: %s", e)

    # Static-widget binding: stat/KPI/progress tiles carrying a literal number and
    # list widgets carrying a hardcoded array (copied from the dashboard exemplar)
    # render fake data. Rebind them to a real op:"aggregate"/op:"list" dataSource
    # when the widget maps confidently to a registry entity. Sibling of the chart
    # guard; conservative (a static widget beats a wrong binding).
    try:
        from services.widget_data_source_guard import bind_static_widgets
        ws = bind_static_widgets(output_dir)
        if ws.get("bound"):
            applied += ws["bound"]
            logger.info(
                "widget_data_source_guard: bound %d static widget(s) to dataSources across %d file(s) (%d skipped) in %s",
                ws["bound"], ws.get("files", 0), ws.get("skipped", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("widget_data_source_guard failed: %s", e)

    # Stub-page backfill: run_page_schema_agent's last-resort floor ships a valid-but-
    # EMPTY page (Stack + one Heading, no dataSources) whenever the LLM overflows/errors
    # across every retry AND the chunked path. It passes every gate and, because a stub
    # FILE now exists, the completeness/continuation passes treat the route as covered and
    # never replace it → the dashboard / a list route ships blank. Detect such stubs for
    # routes the app should populate and fill them deterministically from the REAL
    # registered slugs. Placed AFTER the dataSource guards so the slug set is settled and
    # the bindings it emits are canonical. Idempotent; full pages untouched.
    try:
        from services.stub_page_backfill import backfill_stub_pages
        sb = backfill_stub_pages(str(root))
        if sb.get("backfilled"):
            applied += len(sb["backfilled"])
            logger.info(
                "stub_page_backfill: filled %d empty page(s) in %s: %s",
                len(sb["backfilled"]), output_dir,
                ", ".join(f"{b['id']}({b['kind']})" for b in sb["backfilled"]),
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("stub_page_backfill failed: %s", e)

    # Self-heal: regenerate a missing CRUD workflow that the UI references (a Delete/
    # Edit button pointing at a workflow that was never written), so the reference
    # resolver then sees it as real instead of dead. Deterministic, idempotent.
    try:
        from services.self_heal import heal_missing_workflows
        hres = heal_missing_workflows(str(root))
        if hres.get("healed"):
            applied += len(hres["healed"])
            logger.info("self_heal: regenerated %d missing workflow(s) for %s in %s",
                        len(hres["healed"]), ", ".join(hres.get("entities", [])), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("self_heal failed: %s", e)

    # DB-integrity: rewrite any column emitted as `sql`<type> default …``.notNull()
    # into a real Drizzle builder. That malformed form throws at import time (sql
    # fragments have no builder methods) and hard-crashes BOTH migrate and seed.
    try:
        from services.drizzle_column_guard import guard_drizzle_columns
        cg = guard_drizzle_columns(root)
        if cg.get("fixed"):
            applied += cg["fixed"]
            logger.info("drizzle_column_guard: rewrote %d sql`…`-as-column def(s) in %s: %s",
                        cg["fixed"], output_dir,
                        ", ".join(f"{c['file']}:{c['column']}" for c in cg["changes"]))
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("drizzle_column_guard failed: %s", e)

    # DB-integrity: CHECK constraints written as a plain string instead of a
    # `sql`…`` template make drizzle-kit push abort the WHOLE migration
    # (`sql2.toQuery is not a function`) — no tables, then seed fails on `users`.
    try:
        from services.drizzle_check_guard import guard_check_constraints
        ck = guard_check_constraints(str(root))
        if ck.get("fixed"):
            applied += ck["fixed"]
            logger.info("drizzle_check_guard: wrapped %d string CHECK condition(s) in sql`` across %d file(s) in %s",
                        ck["fixed"], ck.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("drizzle_check_guard failed: %s", e)

    # DB-integrity: align FK column types with their referenced PK so the
    # migration can create the constraints (and seeding actually inserts rows).
    try:
        from services.fk_type_guard import guard_fk_types
        res = guard_fk_types(root)
        if res.get("fixed"):
            applied += res["fixed"]
            logger.info(
                "fk_type_guard: fixed %d FK column type(s) in %s: %s",
                res["fixed"], output_dir,
                ", ".join(f"{c['file']}:{c['column']} {c['from']}→{c['to']}"
                          for c in res["changes"]),
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("fk_type_guard failed: %s", e)

    # DB-data: synthesize real sample rows into contracts/seed-plan.json so the
    # shipped seeder actually populates the domain tables (it reads seed_data /
    # sample_data — a dict no generator filled, so apps shipped EMPTY). Runs AFTER
    # fk_type_guard so FK column types are settled before rows reference them.
    try:
        from services.seed_synthesizer import synthesize_seed_rows
        sres = synthesize_seed_rows(str(root))
        if sres.get("rows_total"):
            applied += sres["rows_total"]
            logger.info(
                "seed_synthesizer: synthesized %d sample row(s) across %d table(s) in %s",
                sres["rows_total"], sres["tables"], output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("seed_synthesizer failed: %s", e)

    # Presentation: rewrite hand-rolled label/value detail rows into the compact
    # DescriptionList component so record-detail pages/drawers don't read archaic.
    try:
        from services.detail_polish import polish_detail_schemas
        dres = polish_detail_schemas(root)
        if dres.get("converted"):
            applied += dres["converted"]
            logger.info("detail_polish: modernised %d detail page(s) in %s (%s)",
                        dres["converted"], output_dir, ", ".join(dres["changed_files"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("detail_polish failed: %s", e)

    # Create-route coverage — guarantee every entity list has a /[segment]/new
    # create form, and repoint New buttons that point at the list route instead of
    # the create route (why "New" opened nothing). Runs before form_scaffold so
    # the synthesized minimal form gets its fields populated.
    try:
        from services.ensure_edit_routes import ensure_create_routes
        cres = ensure_create_routes(str(root))
        if cres.get("created") or cres.get("buttons"):
            applied += cres.get("created", 0) + cres.get("buttons", 0)
            logger.info("ensure_create_routes: created %d create form(s), repointed %d New button(s) in %s",
                        cres.get("created", 0), cres.get("buttons", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_create_routes failed: %s", e)

    # Payment-methods surface — for any app whose plan implies collecting
    # cards (PaymentMethod entity, commerce-flagged entity, or a booking/
    # session/order with an amount column), guarantee a discoverable
    # /settings/payment-methods list + add-card form + nav entry.
    # Idempotent, LLM-authored pages are never overwritten.
    try:
        from services.payment_feature import ensure_payment_surface
        pres = ensure_payment_surface(str(root))
        if pres.get("surfaces_emitted", 0) > 0:
            applied += pres["surfaces_emitted"]
            logger.info(
                "payment_feature: emitted %d surface(s) in %s (%s), nav_updated=%s",
                pres["surfaces_emitted"],
                output_dir,
                pres.get("reason"),
                pres.get("nav_updated"),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("payment_feature skipped: %s", e)

    # Workflow launch forms — for a manual workflow whose entry action is a
    # db_insert dispatched by a BARE Button (empty payload → NOT-NULL crash),
    # generate a trigger-input FORM page collecting the insert's columns and
    # repoint the launcher button to NAVIGATE to it. Same neighborhood as
    # ensure_create_routes (both build form pages + repoint buttons).
    try:
        from services.workflow_launch_forms import ensure_workflow_launch_forms
        import json as _json
        _reg_path = root / "registry.json"
        _reg = _json.loads(_reg_path.read_text()) if _reg_path.exists() else {}
        _wlf_routes = ensure_workflow_launch_forms(str(root), _reg)
        if _wlf_routes:
            applied += len(_wlf_routes)
            logger.info("workflow_launch_forms: created %d trigger form(s) in %s: %s",
                        len(_wlf_routes), output_dir, ", ".join(_wlf_routes))
    except Exception as e:  # noqa: BLE001
        logger.warning("workflow_launch_forms skipped: %s", e)

    # Slice E T4 — inject send_notification before every user_task /
    # approval step in plan.json so the assignee actually learns a
    # task is waiting. Runs BEFORE the workflow-form and orphan-wiring
    # passes so those see the enriched step list. Idempotent.
    try:
        from services.task_notification_defaults import (
            inject_missing_notifications_in_file,
        )
        _pln = root / "contracts" / "plan.json"
        if not _pln.exists():
            _pln = root / "plan.json"
        _tn = inject_missing_notifications_in_file(str(_pln))
        if _tn.get("ok") and _tn.get("inserted"):
            applied += int(_tn["inserted"])
            logger.info(
                "task_notification_defaults: inserted %d notification(s) "
                "into %d workflow(s) in %s",
                _tn["inserted"], _tn.get("workflows_touched", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("task_notification_defaults skipped: %s", e)

    # Slice D — orphan workflow auto-wiring pass. Runs AFTER
    # workflow_launch_forms so we only try to wire orphans that pass
    # didn't already synthesize a launcher for. Finds every workflow no
    # Form.props.workflow targets, scores unwired forms by input-name
    # overlap, wires the strongest match. Never overwrites an existing
    # wire. Any residual orphan is logged as a warning — Slice A will
    # promote that to a hard fail once the plan-level contract lands.
    try:
        from services.orphan_wiring_pass import wire_orphan_workflows
        _ow = wire_orphan_workflows(str(root))
        _wired = _ow.get("wired") or []
        _unresolved = _ow.get("unresolved") or []
        if _wired:
            applied += len(_wired)
            logger.info(
                "orphan_wiring_pass: wired %d orphan workflow(s) in %s: %s",
                len(_wired), output_dir,
                ", ".join(f"{w['workflow']}→{w['page_route']}" for w in _wired),
            )
        if _unresolved:
            logger.warning(
                "orphan_wiring_pass: %d workflow(s) still orphaned in %s: %s",
                len(_unresolved), output_dir,
                ", ".join(u["workflow"] for u in _unresolved),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("orphan_wiring_pass skipped: %s", e)

    # File-first upload forms (doc-intel reference contract) — a
    # workflow-bound form with a FileUpload supplies only the FILE; the
    # metadata columns come from FileUpload's hidden companion inputs
    # (wired to the real column names), the uploader FK from $user.id,
    # timestamps from $now. Kills the visible-vs-hidden originalFilename
    # collision that rejected every upload. Runs AFTER wiring passes so
    # it sees the final form↔workflow pairing.
    try:
        from services.file_first_forms import apply_file_first_forms
        _ff = apply_file_first_forms(str(root))
        if _ff["summary"]["forms_rewritten"]:
            applied += _ff["summary"]["forms_rewritten"]
            logger.info(
                "file_first_forms: rewrote %d upload form(s), %d workflow(s)",
                _ff["summary"]["forms_rewritten"],
                _ff["summary"]["workflows_rewritten"])
    except Exception as e:  # noqa: BLE001
        logger.warning("file_first_forms skipped: %s", e)

    # Slice A T7 + T8 — SUBMIT-AUTHORITY guards. Run AFTER all wiring
    # passes so we only report gaps that survived every synthesis
    # attempt. v1 logs warnings; v2 will hard-fail the pipeline on any
    # violation (once observation confirms the wiring passes catch the
    # common cases).
    try:
        from services.submit_authority_guards import (
            workflow_completeness_guard, form_target_guard,
        )
        _wc = workflow_completeness_guard(str(root))
        if not _wc["ok"]:
            logger.warning(
                "[submit-authority] %d orphan workflow(s) in %s: %s",
                len(_wc["violations"]), output_dir,
                ", ".join(v["name"] for v in _wc["violations"]),
            )
        _ft = form_target_guard(str(root))
        if not _ft["ok"]:
            logger.warning(
                "[submit-authority] %d form(s) without a submit target in "
                "%s: %s",
                len(_ft["violations"]), output_dir,
                ", ".join(v.get("route") or v.get("path")
                          for v in _ft["violations"]),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("submit_authority_guards skipped: %s", e)

    # Event-only workflow buttons — a bare page Button wired to a workflow whose
    # trigger is db_change/api_event/schedule (event-driven) dispatches an EMPTY
    # payload on click (no record to hand over) and silently does nothing. Remove
    # such dead buttons (or disable them). Manual-trigger buttons and buttons on a
    # record-detail/[id] page (which HAS a record context) are left untouched.
    # Runs after launch-form repoints so the button set is settled.
    try:
        from services.workflow_trigger_button_guard import neutralize_event_only_buttons
        tb = neutralize_event_only_buttons(str(root))
        _tb_fixes = len(tb.get("removed", [])) + len(tb.get("disabled", []))
        if _tb_fixes:
            applied += _tb_fixes
            logger.warning(
                "workflow_trigger_button_guard: neutralized %d event-only button(s) "
                "(removed %d, disabled %d) across %d file(s) in %s",
                _tb_fixes, len(tb.get("removed", [])), len(tb.get("disabled", [])),
                tb.get("files", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("workflow_trigger_button_guard failed: %s", e)

    # Form → workflow input map backfill — the fix for the "nothing
    # happens when I save" bug. action_contract_guard above populates
    # ``unmapped_fields`` when a form has fields the workflow's mutation
    # step doesn't receive; this pass adds each of those fields to the
    # workflow's ``values`` map as ``{{field}}`` interpolation so the
    # runtime actually persists them. Must run AFTER
    # action_contract_guard so unmapped_fields is populated.
    try:
        from services.workflow_input_map_backfill import (
            backfill_workflow_input_maps,
            is_input_map_backfill_enabled,
        )
        if is_input_map_backfill_enabled():
            wim = backfill_workflow_input_maps(str(root))
            if wim.get("fields_added", 0) > 0:
                applied += wim["fields_added"]
                logger.info(
                    "workflow_input_map_backfill: +%d field(s) across "
                    "%d workflow(s) in %s: %s",
                    wim["fields_added"],
                    len(wim.get("workflows_touched") or []),
                    output_dir,
                    ", ".join(wim.get("workflows_touched") or []),
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("workflow_input_map_backfill skipped: %s", e)

    # After the input-map backfill has painted `{{field}}` mustache bindings
    # onto mutation-node values, strip any that don't correspond to a real
    # processVariable — a stale `{{isActive}}` on a boolean column crashes
    # the db_insert at runtime and silently drops the row. Runs immediately
    # after the backfill so no downstream pass ships the broken values.
    try:
        from services.workflow_values_clean_guard import clean_workflow_values
        wvc = clean_workflow_values(str(root))
        if wvc.get("values_removed", 0) > 0:
            applied += wvc["values_removed"]
            logger.info(
                "workflow_values_clean_guard: dropped %d stale binding(s) "
                "across %d workflow(s) in %s: %s",
                wvc["values_removed"],
                len(wvc.get("workflows_touched") or []),
                output_dir,
                ", ".join(wvc.get("workflows_touched") or []),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("workflow_values_clean_guard skipped: %s", e)

    # Plain-string mode of the same "workflow writes to columns no form
    # provides" bug: the CRUD generator emits `{"isVerified": "isVerified"}`
    # for every writable column, but the create form omits system-managed
    # fields (isVerified / verifiedAt / totalSessions). At runtime the
    # dispatch has no value, db_insert writes undefined into a typed column,
    # Postgres rejects, row silently dropped. Cross-reference workflow
    # values against action-contract input_maps and drop any orphan process-
    # variable references. Runs AFTER workflow_values_clean_guard (which
    # handles the mustache leg) and AFTER action_contract_guard (which
    # populates the input_maps we read).
    try:
        from services.workflow_form_field_pruner import prune_workflow_form_fields
        wff = prune_workflow_form_fields(str(root))
        if wff.get("values_removed", 0) > 0:
            applied += wff["values_removed"]
            logger.info(
                "workflow_form_field_pruner: dropped %d unmapped column(s) "
                "across %d workflow(s) in %s: %s",
                wff["values_removed"],
                len(wff.get("workflows_touched") or []),
                output_dir,
                ", ".join(wff.get("workflows_touched") or []),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("workflow_form_field_pruner skipped: %s", e)

    # Form completeness — scaffold an input for EVERY editable column (optional
    # ones + FK dropdowns), not just required ones, so create/edit forms aren't
    # half-empty. Runs before the type pass so new fields also get typed.
    try:
        from services.form_scaffold import scaffold_forms
        fres = scaffold_forms(str(root))
        if fres.get("added"):
            applied += fres["added"]
            logger.info("form_scaffold: added %d field(s) across %d form(s) in %s",
                        fres["added"], fres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("form_scaffold failed: %s", e)

    # FK dropdown repair — fix Select dataSources that point at a guessed/wrong
    # entity (planId → "Plan" instead of "MembershipPlan"), which left the dropdown
    # empty because /api/data/<name> resolved to nothing.
    try:
        from services.form_scaffold import repair_fk_dropdowns
        rres = repair_fk_dropdowns(str(root))
        if rres.get("repaired"):
            applied += rres["repaired"]
            logger.info("repair_fk_dropdowns: fixed %d FK dropdown(s) in %d file(s) in %s",
                        rres["repaired"], rres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("repair_fk_dropdowns failed: %s", e)

    # Required markers — stamp validators.required (the `*`) on create/edit form
    # fields whose backing column is NOT NULL per the registry, so an LLM-authored
    # form that omitted them gets the same empty-submit guard the built forms have.
    try:
        from services.form_scaffold import ensure_required_markers
        rmres = ensure_required_markers(str(root))
        if rmres.get("marked"):
            applied += rmres["marked"]
            logger.info("ensure_required_markers: marked %d field(s) across %d file(s) in %s",
                        rmres["marked"], rmres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_required_markers failed: %s", e)

    # Enum dropdowns — upgrade a plain Input over an enum-ish column (status/stage/
    # priority) into a Select with real options (registry enum_values → workflow
    # literals → a conservative curated dictionary), so an LLM form's free-text status
    # box becomes a dropdown. Open-ended fields (nationality, notes) stay Input.
    try:
        from services.form_scaffold import ensure_enum_selects
        eres = ensure_enum_selects(str(root))
        if eres.get("converted"):
            applied += eres["converted"]
            logger.info("ensure_enum_selects: converted %d field(s) to Select across %d file(s) in %s",
                        eres["converted"], eres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_enum_selects failed: %s", e)

    # Humanize raw class-name labels in nav-flow.json (personas.screens,
    # personas.jobs, pages.title). Anything shaped like ``MemberSchedulePage``
    # gets rewritten from its route's last meaningful segment so the persona
    # sub-nav pills read "Schedule" instead of "MemberSchedulePage".
    try:
        from services.humanize_nav_flow_labels import run as _run_humanize_nav
        hnres = _run_humanize_nav(str(root))
        if hnres.get("rewritten"):
            applied += hnres["rewritten"]
            logger.info(
                "humanize_nav_flow_labels: rewrote %d raw class-name label(s) in %s",
                hnres["rewritten"], output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("humanize_nav_flow_labels failed: %s", e)

    # Fold hallucinated chart component types (LineChart, AreaChart,
    # BarChart, PieChart, ...) into Chart + chartType prop. The
    # library exposes ONE chart component with a chartType prop; the
    # LLM occasionally emits recharts-style split names that the
    # renderer's registry has no entry for → renders as a "Component X
    # is not registered" placeholder. See services/chart_type_alias.py.
    try:
        from services.chart_type_alias import apply_chart_type_alias
        cres = apply_chart_type_alias(str(root))
        if cres.get("rewritten"):
            applied += cres["rewritten"]
            logger.info(
                "chart_type_alias: rewrote %d chart node(s) across %d file(s)",
                cres["rewritten"], cres["patched"],
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("chart_type_alias failed: %s", e)

    # Apply structured user directives (Preset, row-click, filter dims) that
    # the plan_directive_parser pulled from the prompt. See docstring in
    # services/apply_hints_to_pages.py — Slice 1 of the requirement-as-
    # central-piece direction.
    try:
        from services.apply_hints_to_pages import apply_hints_to_pages
        hres = apply_hints_to_pages(str(root))
        if hres.get("patched"):
            applied += hres["patched"]
            logger.info(
                "apply_hints_to_pages: patched %d page(s) — row_click=%d, filter_bar=%d",
                hres["patched"], hres.get("row_click", 0), hres.get("filter_bar", 0),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("apply_hints_to_pages failed: %s", e)

    # Requirement-fidelity critic (Slice 3 of requirement-as-central-piece).
    # Runs LAST so the report reflects post-repair state. Reads
    # requirement.json + shipped schemas, scores each parsed directive
    # (visual_preset, archetype, row_click, filters, gauges, chart_types),
    # fires deterministic auto-repairs for the fixable ones, then re-scores
    # and writes contracts/requirement-fidelity.json. Smith reads that
    # report to surface residual misses on the next turn.
    try:
        from services.requirement_fidelity_critic import run as _fidelity_run
        _rep = _fidelity_run(str(root), auto_repair=True)
        _summary = _rep.get("summary") or {}
        if _summary.get("missing", 0) or _summary.get("partial", 0):
            logger.info(
                "requirement-fidelity: ok=%d missing=%d partial=%d (see requirement-fidelity.json)",
                _summary.get("ok", 0), _summary.get("missing", 0), _summary.get("partial", 0),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("requirement-fidelity critic failed: %s", e)

    # Alias unknown component types (e.g. LLM-emitted ``DateTimePicker``)
    # to the nearest registered library component. Runs BEFORE
    # semantic_field_types so that pass sees the canonical type. Skips
    # any alias whose target isn't in the compiled registry — never
    # rewrites to a name the renderer would also drop.
    try:
        from services.alias_unknown_components import run as _run_alias_unknown
        ares = _run_alias_unknown(str(root))
        if ares.get("aliased"):
            applied += ares["aliased"]
            logger.info(
                "alias_unknown_components: rewrote %d node(s) across %d file(s) in %s",
                ares["aliased"], ares["files"], output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("alias_unknown_components failed: %s", e)

    # Semantic field types — enum→Select (with real options), numeric→NumberInput,
    # date→DatePicker, etc., so forms aren't a wall of text inputs.
    try:
        from services.semantic_field_types import apply_semantic_field_types
        sres = apply_semantic_field_types(str(root))
        if sres.get("retyped"):
            applied += sres["retyped"]
            logger.info("semantic_field_types: re-typed %d field(s) across %d file(s) in %s",
                        sres["retyped"], sres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("semantic_field_types failed: %s", e)

    # Spec C4 — motion + responsive CSS tokens. Appends
    # --motion-fast/medium/slow-ms + --ease-out/--ease-in-out + a
    # prefers-reduced-motion override to globals.css so brief-authored
    # motion values reach the runtime.
    try:
        from services.motion_tokens_writer import write_motion_tokens, is_enabled as _mt_on
        if _mt_on():
            mtres = write_motion_tokens(str(root))
            if mtres.get("written"):
                applied += 1
                logger.info("motion_tokens_writer: appended motion+responsive block to globals.css in %s", output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("motion_tokens_writer failed: %s", e)

    # Spec C2 — signature moves. Walks page schemas, applies each
    # brief-declared move's renderer to matching nodes.
    try:
        from services.apply_signature_moves import apply_signature_moves, is_enabled as _sm_on
        if _sm_on():
            smres = apply_signature_moves(str(root))
            if smres.get("moves_applied"):
                applied += smres["moves_applied"]
                logger.info("apply_signature_moves: %d move(s) across %d file(s); unknown=%s in %s",
                            smres["moves_applied"], smres["files"],
                            smres.get("unknown_kinds"), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("apply_signature_moves failed: %s", e)

    # Spec C9 — monogram logo set. Emits public/logo.svg + siblings so
    # every app ships a functional brand mark. Flag-gated on
    # FORGE_POLISH_LOGO. Reads app_name + brand hex from disk.
    try:
        _lg_on = os.getenv("FORGE_POLISH_LOGO", "0").strip().lower() in ("1", "true", "yes", "on")
        if _lg_on:
            from services.logo_generator import generate_logo_set
            # Resolve inputs with the same fallback chain edge_page_customizer uses.
            import json as _json
            _brief = {}
            _plan = {}
            try:
                bp = root / "src" / "contracts" / "brief.json"
                if bp.is_file():
                    _brief = _json.loads(bp.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                pass
            try:
                pp = root / "src" / "contracts" / "plan.json"
                if pp.is_file():
                    _plan = _json.loads(pp.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                pass
            _app_name = (
                (_plan.get("app_name") if isinstance(_plan, dict) else None)
                or (_plan.get("name") if isinstance(_plan, dict) else None)
                or Path(output_dir).name
            )
            _brand = "#111827"
            if isinstance(_brief, dict):
                _pal = _brief.get("palette") or {}
                if isinstance(_pal, dict) and isinstance(_pal.get("brand"), str):
                    _brand = _pal["brand"]
            _radius_kind = "soft_8"
            if isinstance(_brief, dict):
                _lay = _brief.get("layout") or {}
                if isinstance(_lay, dict) and isinstance(_lay.get("radius"), str):
                    _radius_kind = _lay["radius"]
            lgres = generate_logo_set(
                str(root), app_name=str(_app_name),
                brand_hex=_brand, radius_kind=_radius_kind,
            )
            if lgres.get("files"):
                applied += lgres["files"]
                logger.info("logo_generator: %d SVG(s) for '%s' (letter=%s, brand=%s) in %s",
                            lgres["files"], _app_name, lgres.get("letter"),
                            lgres.get("brand"), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("logo_generator failed: %s", e)

    # Spec C9 (illustrations half) — upgrade bare EmptyState nodes to
    # the branded IllustratedEmpty component the library already ships.
    # Same S9 flag gate as the logo generator. Route-aware kind picking
    # keeps different empty-state contexts from stamping the same glyph.
    try:
        from services.illustrated_empty_pass import run as _run_illus
        _ires = _run_illus(str(root))
        if _ires.get("total_upgrades"):
            applied += _ires["total_upgrades"]
            logger.info(
                "illustrated_empty_pass: %d upgrade(s) across %d page(s) in %s",
                _ires["total_upgrades"], _ires["pages_upgraded"], output_dir,
            )
        elif _ires.get("skipped_reason"):
            logger.debug("illustrated_empty_pass skipped: %s",
                         _ires["skipped_reason"])
    except Exception as e:  # noqa: BLE001
        logger.warning("illustrated_empty_pass failed: %s", e)

    # Spec C4 + C8 — inject the library's interactions + theme-dark
    # stylesheets into the generated app's globals.css. Flag-gated
    # per-slice (FORGE_POLISH_INTERACTIONS / FORGE_POLISH_DARK_MODE);
    # no-op when both are off. Sentinel-bracketed injection is idempotent.
    try:
        from services.interactions_css_inject import inject_polish_stylesheets
        _csres = inject_polish_stylesheets(str(root))
        _inj = _csres.get("injected") or []
        if _inj:
            logger.info("interactions_css_inject: %s injected into globals.css in %s",
                        ", ".join(_inj), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("interactions_css_inject failed: %s", e)

    # Spec C5 — edge pages. Substitute {{app_name}} / {{app_initial}} /
    # {{home_route}} in the copied not-found / error / forbidden /
    # maintenance templates + EdgePageFrame component. Flag-gated
    # (FORGE_POLISH_EDGE_PAGES); no-op when off. Runs early so any
    # later post-gen pass that inspects those files sees final copy.
    try:
        from services.edge_page_customizer import customize_edge_pages, is_enabled
        if is_enabled():
            epres = customize_edge_pages(str(root))
            if epres.get("files"):
                applied += epres["files"]
                logger.info("edge_page_customizer: rewrote %d file(s) with app_name=%s home=%s in %s",
                            epres["files"], epres.get("app_name"), epres.get("home_route"), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("edge_page_customizer failed: %s", e)

    # Residual-placeholder guard. Runs immediately after the substituter so
    # it validates that pass's work, and catches the case the substituter
    # cannot: a pass that did not RUN at all (older app, skipped post-gen,
    # a new template added without a matching substituter).
    #
    # A `{{token}}` left in a .tsx is not a placeholder to the compiler — it
    # is the object literal `{token}`, which typechecks and then throws
    # `ReferenceError` at prerender. It passes every other gate and fails
    # only in `next build` on the deploy. Report-only here; the artifact is
    # what downstream gates read.
    try:
        from services.residual_placeholder_guard import apply_residual_placeholder_guard
        apply_residual_placeholder_guard(root)
    except Exception as e:  # noqa: BLE001 — a guard must never block generation
        logger.warning("residual_placeholder_guard failed: %s", e)

    # Spec B4 — context side-rail. Wrap single-primary-FK create/edit forms
    # in Split[2:1] with a Card+DescriptionList context panel on the right,
    # so users always see what parent record they're filling the form for.
    # Flag-gated (FORGE_FORM_CONTEXT_PANEL); no-op when off. Runs AFTER
    # ensure_enum_selects + semantic_field_types so the FK Selects it detects
    # are already in their final shape.
    try:
        from services.context_panel_builder import inject_context_panels
        cpres = inject_context_panels(str(root))
        if cpres.get("wrapped"):
            applied += cpres["wrapped"]
            logger.info("context_panel_builder: wrapped %d form(s) in %d file(s) in %s",
                        cpres["wrapped"], cpres["files"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("context_panel_builder failed: %s", e)

    # Edit routes — the pipeline emits new + detail schemas but not /[id]/edit,
    # so Edit buttons navigate to a route that doesn't exist. Synthesize the edit
    # form from the create form, re-register, and wire Edit buttons to it.
    try:
        from services.ensure_edit_routes import ensure_edit_routes
        eres = ensure_edit_routes(str(root))
        if eres.get("created") or eres.get("buttons"):
            applied += eres.get("created", 0) + eres.get("buttons", 0)
            logger.info("ensure_edit_routes: created %d edit schema(s), wired %d Edit button(s) in %s",
                        eres.get("created", 0), eres.get("buttons", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_edit_routes failed: %s", e)

    # FK display labels — show a table's FK columns as the referenced record's name
    # (memberId → "Alice Johnson"), not a raw UUID. Emits src/lib/fk-labels.json (the
    # data-engine attaches <fkProp>Label to each row) and repoints FK columns at it.
    try:
        from services.fk_label_columns import relabel_fk_columns
        fl = relabel_fk_columns(str(root))
        if fl.get("relabeled"):
            applied += fl["relabeled"]
            logger.info("fk_label_columns: relabeled %d FK column(s) across %d file(s) in %s",
                        fl["relabeled"], fl.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("fk_label_columns failed: %s", e)

    # next.config normalization — the schema/code agents emit their own next.config
    # and the LLM tends to pile jsdom + its subtree into transpilePackages, which
    # bundles jsdom and breaks at runtime (ENOENT default-stylesheet.css on every
    # HTML-sanitizing page). Re-assert the one authoritative config (jsdom stays a
    # serverExternalPackage) and drop conflicting .ts/.mjs variants.
    try:
        from services.next_config_guard import normalize_next_config
        nc = normalize_next_config(str(root))
        if nc.get("normalized") or nc.get("removed_variants"):
            applied += nc.get("normalized", 0)
            logger.info("next_config_guard: normalized=%d, removed %d variant(s) in %s",
                        nc.get("normalized", 0), nc.get("removed_variants", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("next_config_guard failed: %s", e)

    # Row navigation — a list table with a detail route but no `rowHref` leaves
    # row-click dead (the detail drawer never opens). Point the entity table's rows
    # at /entity/{{id}} so clicking a row opens its detail overlay.
    try:
        from services.table_row_nav_guard import guard_table_row_nav
        tr = guard_table_row_nav(str(root))
        if tr.get("wired"):
            applied += tr["wired"]
            logger.info("table_row_nav_guard: wired %d list table(s) to detail routes across %d file(s) in %s",
                        tr["wired"], tr.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("table_row_nav_guard failed: %s", e)

    # Auth gate — the scaffold's (dashboard) layout unconditionally redirects to
    # /login. Honour the app's authGated decision: a public app (authGated=false)
    # must start at / rather than be bounced to a login page. Gated apps unchanged.
    try:
        from services.auth_gate_guard import guard_auth_gate
        ag = guard_auth_gate(str(root))
        if ag.get("patched"):
            applied += ag["patched"]
            logger.info("auth_gate_guard: neutralised login gate for public app in %s", output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("auth_gate_guard failed: %s", e)

    # Nav transitions — build the authoritative connection graph into
    # nav-flow.transitions from the generated schemas (+ auth-flow edges). Runs
    # after route reconciliation so targets resolve to the corrected routes.
    # This is the flow the Pages/Nav editor renders and edits.
    try:
        from services.nav_transitions import build_transitions
        nt = build_transitions(str(root))
        if nt.get("transitions"):
            logger.info("nav_transitions: wrote %d transition(s) in %s", nt["transitions"], output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("nav_transitions failed: %s", e)

    # Surface wrapping — a Table/Chart/list dropped straight into a Stack/Section
    # renders flush against the container edges (content touching the boundary).
    # Pages reachable from the shell menu must not carry the Figma full-bleed
    # escape (`_figmaDerived`) — its fixed z-[60] layer covers the shell header
    # and makes chrome (hamburger, user menu) unclickable.
    try:
        from services.figma_overlay_strip import strip_figma_overlay
        fo = strip_figma_overlay(str(root))
        if fo.get("stripped"):
            applied += fo["stripped"]
            logger.info("figma_overlay_strip: removed _figmaDerived from %d in-shell page(s): %s",
                        fo["stripped"], ", ".join(fo["files"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("figma_overlay_strip failed: %s", e)

    # Wrap bare data-display nodes in a padded Card so they get a gutter, unless
    # they're already inside a surface.
    try:
        from services.surface_wrap_guard import wrap_bare_data_displays
        sw = wrap_bare_data_displays(str(root))
        if sw.get("wrapped"):
            applied += sw["wrapped"]
            logger.info("surface_wrap_guard: wrapped %d bare data-display(s) in cards across %d file(s) in %s",
                        sw["wrapped"], sw.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("surface_wrap_guard failed: %s", e)

    # Chart data — Charts are frequently emitted with a HARDCODED literal `data`
    # array of made-up rows (copied from the dashboard exemplar), so they render
    # fake numbers. Convert each to a real op:"series" (GROUP BY) dataSource bound
    # to the chart, when it maps confidently to a real entity/column. Runs before
    # the reference resolver so the new series sources get validated.
    try:
        from services.chart_data_source_guard import guard_chart_data_sources
        cds = guard_chart_data_sources(str(root))
        if cds.get("converted"):
            applied += cds["converted"]
            logger.info("chart_data_source_guard: bound %d chart(s) to series dataSources across %d file(s) (%d skipped) in %s",
                        cds["converted"], cds.get("files", 0), cds.get("skipped", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("chart_data_source_guard failed: %s", e)

    # Reference resolver — the FINAL authority. Resolve every remaining schema
    # reference (entity/dataSource/optionsFrom) against the extracted registry
    # (reality), derive-first then fuzzy, and write contracts/references-report.json
    # so any unresolved reference is visible instead of a silent empty dropdown.
    try:
        from services.schema_references import resolve_schema_references
        rr = resolve_schema_references(str(root))
        if rr.get("resolved"):
            applied += rr["resolved"]
        if rr.get("resolved") or rr.get("unresolved"):
            logger.info("schema_references: resolved %d (derived %d, fuzzy %d), unresolved %d in %s",
                        rr.get("resolved", 0), rr.get("derived", 0), rr.get("fuzzy", 0),
                        rr.get("unresolved", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_references failed: %s", e)

    # FINAL list-binding reconciliation — MUST be the last binding pass. The
    # deterministic list builder emits a page where the list dataSource NAME and the
    # Table rows-binding share one token derived from the route slug (`drives` ↔
    # `{{drives}}`) — internally consistent, so the earlier reconcile_list_sources
    # (above, right after the schema/table guards) correctly sees NO mismatch. But
    # `schema_references` then canonicalises that dataSource NAME to the real entity
    # slug (`drives` → `recruitmentDrives`) WITHOUT rewriting the rows-binding, which
    # only its `name_remap` handles for `optionsFrom.source` — not Table `rows`.
    # That leaves `{{drives}}` dangling against a `recruitmentDrives` source → the
    # table renders EMPTY (the exact `output/afwn8nya` /drives + /inbox bug). Re-run
    # the reconcile HERE, after every page-emitting/renaming pass, so any binding a
    # later pass orphaned is healed against the settled dataSource names. Idempotent:
    # a no-op when the first pass already left everything consistent.
    try:
        from services.list_data_source_guard import reconcile_list_sources
        ls2 = reconcile_list_sources(str(root))
        _ls2_fixes = len(ls2.get("binding_remapped", [])) + len(ls2.get("source_remapped", []))
        if _ls2_fixes:
            applied += _ls2_fixes
            logger.info(
                "list_data_source_guard (final): healed %d binding(s) + %d source(s) "
                "orphaned by dataSource renaming across %d file(s) in %s",
                len(ls2["binding_remapped"]), len(ls2["source_remapped"]),
                ls2.get("files_changed", 0), output_dir,
            )
        if ls2.get("binding_unresolved") or ls2.get("source_unresolved"):
            logger.warning(
                "list_data_source_guard (final): UNRESOLVED %d binding(s), %d source(s) in %s",
                len(ls2.get("binding_unresolved", [])),
                len(ls2.get("source_unresolved", [])), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("list_data_source_guard (final) failed: %s", e)

    # Dashboard completeness — a dashboard page with fewer than N content
    # sections gets a deterministic top-up: KPI row from primary entities,
    # quick-actions row, recent-items card. Uses only registered library
    # components + real plan entities. Root-cause fix for B-022.10 (bare
    # dashboard UI) — additive + idempotent. Runs before route_intent_apply
    # so any singleton/scope collapse takes precedence on non-dashboard
    # routes.
    # Maquette composers are GENERATION-TIME authorities: they re-compose
    # whole pages from maquette files. On a Smith re-apply (force=True)
    # they must NOT run — re-composition silently clobbers the user's /
    # Smith's page edits (the 'my edit never saved' class, see BUG-APPLY-1).
    if not force:
        # A2UI composer (FORGE_A2UI, off by default) gets first refusal on the
        # DASHBOARD. It writes nothing unless the page it composes clears the
        # substance floor for that kind, so a decline leaves the world exactly
        # as the deterministic composers below expect to find it. Adding a
        # second writer to this slot is only safe because the handoff is a
        # gate, not a preference — see services/a2ui_authority.py.
        #
        # Scope is deliberately one kind. Authority works on collection, record
        # and form too (proven live on all four), but each composition is a 2-4
        # minute round trip and one of four live attempts failed on a transient
        # fault a retry cleared. Until that rate is measured, the dashboard is
        # the screen worth spending it on. FORGE_A2UI_SCOPE=pages restores the
        # capped multi-kind loop (FORGE_A2UI_MAX_PAGES, default 4); what the
        # cap skips is logged, never silently dropped.
        a2ui_owned = False
        try:
            from services.a2ui_authority import (
                compose_pages_via_a2ui, is_a2ui_enabled,
            )
            if is_a2ui_enabled():
                a2ui_res = compose_pages_via_a2ui(str(root))
                # Whether the LANDING route was taken, not whether "/" was:
                # a dashboard often lives at /dashboard, and keying on "/"
                # would let the maquette composer overwrite a page A2UI had
                # just successfully written.
                from services.dashboard_anatomy import is_dashboard_route
                a2ui_owned = any(is_dashboard_route(r)
                                 for r in (a2ui_res.get("applied_routes") or []))
                logger.info(
                    "a2ui_authority: composed %d of %d page(s) — %s%s",
                    a2ui_res.get("applied", 0), a2ui_res.get("attempted", 0),
                    ", ".join(a2ui_res.get("applied_routes") or []) or "none",
                    (f" | capped, left to the deterministic composers: "
                     f"{', '.join(a2ui_res['skipped_by_cap'])}")
                    if a2ui_res.get("skipped_by_cap") else "",
                )
                for d in a2ui_res.get("declined") or []:
                    logger.info("a2ui_authority: declined %s — %s",
                                d.get("route"), d.get("reason"))
        except Exception as e:  # noqa: BLE001 — never block generation
            logger.warning("a2ui_authority failed: %s", e)

        # Dashboard-maquette composer — the authority for this slot whenever
        # A2UI above declined, which is every build with FORGE_A2UI off.
        # When the maquette LLM step (pipeline: after plan.json) produced a
        # dashboard-maquette.json, this composer rewrites the dashboard schema
        # deterministically from that content spec (KPI row + primary chart +
        # activity feed + hero). Runs before dashboard_completeness so the
        # completeness top-up finds a rich dashboard and no-ops.
        try:
            from services.apply_dashboard_maquette import apply_maquette_to_dashboard
            maq_res = (
                {"applied": False, "reason": "A2UI composed the landing dashboard"}
                if a2ui_owned else apply_maquette_to_dashboard(str(root))
            )
            if maq_res.get("applied"):
                logger.info(
                    "dashboard_maquette: composed dashboard from maquette — "
                    "%d sections written to %s",
                    maq_res.get("sections_written", 0), maq_res.get("schema_path"),
                )
        except Exception as e:  # noqa: BLE001 — never block generation
            logger.warning("dashboard_maquette apply failed: %s", e)

        # Sub-dashboard composer — owns every dashboard-typed page beyond the
        # landing route (report / analytics / movement / breakdown pages the
        # planner tags ``type: dashboard`` but that fall outside the single
        # landing route the maquette composer claims). Emits inline dataSources
        # so the ``op:"aggregate"`` without ``metrics`` drift class (dz6jba0x
        # ``/mrr-movement`` bug) becomes impossible at emit time. Gated behind
        # the same FORGE_DASHBOARD_AUTHORITY flag as the maquette composer;
        # runs AFTER it so the landing composer wins first.
        try:
            from services.dashboard_authority import is_dashboard_authority_enabled
            if is_dashboard_authority_enabled():
                from services.dashboard_page_composer import compose_sub_dashboards
                # Component names — same source the deterministic dashboard
                # compiler in deterministic_pages.py uses.
                try:
                    from services.library_manifest import load_component_catalog
                    _component_names = set((load_component_catalog() or {}).keys())
                except Exception:  # noqa: BLE001
                    _component_names = set()
                sub_res = compose_sub_dashboards(
                    str(root), component_names=_component_names,
                )
                if sub_res.get("composed"):
                    applied += sub_res["composed"]
                    logger.info(
                        "dashboard_page_composer: composed %d sub-dashboard(s): %s",
                        sub_res["composed"], sub_res.get("written"),
                    )
        except Exception as e:  # noqa: BLE001 — never block generation
            logger.warning("dashboard_page_composer failed: %s", e)

        # Collection-maquette composer — same authority pattern as the
        # dashboard composer. When collection-maquettes.json exists
        # (written by plan_finalize.author_collection_maquettes_if_enabled),
        # this rewrites each targeted collection page schema
        # deterministically from the maquette's decisions (layout, columns,
        # row treatment, hero, filter presets, empty state, footer,
        # signature moves). No-op when the file is missing; per-page failure
        # doesn't stop the batch. Runs BEFORE dashboard_completeness because
        # the two touch disjoint pages, but keeping the maquette-first order
        # documents the "maquette is authority" pattern uniformly.
        try:
            from services.apply_collection_maquette import apply_maquettes_to_collections
            cmq = apply_maquettes_to_collections(str(root))
            if cmq.get("applied"):
                logger.info(
                    "collection_maquette: composed %d collection page(s) from maquettes",
                    cmq.get("applied", 0),
                )
        except Exception as e:  # noqa: BLE001 — never block generation
            logger.warning("collection_maquette apply failed: %s", e)

        # Record-maquette composer — same pattern for form / edit / view
        # detail pages. Reads record-maquettes.json + rewrites each targeted
        # record page schema (Form + FormSection cards, or read-only
        # DescriptionList sections in view mode) with per-field control
        # hints, hero variants, and footer bands honoured.
        try:
            from services.apply_record_maquette import apply_maquettes_to_records
            rmq = apply_maquettes_to_records(str(root))
            if rmq.get("applied"):
                logger.info(
                    "record_maquette: composed %d record page(s) from maquettes",
                    rmq.get("applied", 0),
                )
        except Exception as e:  # noqa: BLE001 — never block generation
            logger.warning("record_maquette apply failed: %s", e)


    # ── Post-authority repair band ───────────────────────────────────
    # Section layout, first — it is a normalization over the emitted schema,
    # not a repair of a mistake, and every guard below reads better against a
    # settled layout. Rules used to live inside the A2UI binder, so the
    # deterministic composers (which own every dashboard A2UI declines, plus
    # sub-dashboards, collections and records) shipped the cramped version of
    # the same page. Stating them once here is what stops the next composer
    # from having to learn them a third time.
    try:
        from services.section_layout import normalize_section_layout
        sl = normalize_section_layout(str(root))
        if sl.get("changed"):
            applied += sl["changed"]
            logger.info(
                "section_layout: reshaped sections on %d page(s) in %s",
                sl["changed"], output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("section_layout failed: %s", e)

    # A KPI may not claim a format its own metric cannot produce. "Utilization
    # Rate" shipped as `percent` over a plain row `count`, so 10 rows rendered
    # as 1,000%. Runs here, after every composer, because the offending pair
    # (tile format + dataSource fn) is only assembled once the page is final.
    try:
        import json as _json
        from services.kpi_format_honesty import reconcile_kpi_formats
        fixed_pages = 0
        for sp in Path(root, "src", "schemas").glob("**/*.json"):
            try:
                page = _json.loads(sp.read_text())
            except Exception:  # noqa: BLE001 — not every json here is a page
                continue
            if not isinstance(page, dict) or "root" not in page:
                continue
            rep = reconcile_kpi_formats(page)
            if rep["changed"]:
                sp.write_text(_json.dumps(page, indent=2))
                fixed_pages += 1
                applied += rep["changed"]
                for note in rep["notes"]:
                    logger.info("kpi_format_honesty: %s", note)
        if fixed_pages:
            logger.info("kpi_format_honesty: corrected %d page(s) in %s",
                        fixed_pages, output_dir)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("kpi_format_honesty failed: %s", e)

    # The completeness rule ("every entity reachable") was being satisfied
    # twice: /admin/employees reached Employees, and a bare /employees page was
    # appended anyway, so the sidebar showed `employees` above `Employees`.
    # Coverage is a question about the entity, not the URL — dedupe on that,
    # and give a written label to any slug page that is genuinely the only way
    # in (stranding an entity is the failure the rule exists to prevent).
    try:
        from services.nav_entity_dedup import reconcile_nav_flow
        for nf in (Path(root, "src", "contracts", "nav-flow.json"),
                   Path(root, "contracts", "nav-flow.json")):
            rep = reconcile_nav_flow(str(nf))
            if rep["dropped"] or rep["renamed"]:
                applied += rep["dropped"] + rep["renamed"]
                for note in rep["notes"]:
                    logger.info("nav_entity_dedup: %s", note)
                try:
                    from services.shell_menu_sync import sync_shell_menu
                    sync_shell_menu(str(root))
                except Exception as e:  # noqa: BLE001
                    logger.warning("nav_entity_dedup: menu resync failed: %s", e)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("nav_entity_dedup failed: %s", e)

    # A grid row is as wide as its narrowest column and as tall as its tallest
    # child, so a 4-column table in a third of the page bleeds and an
    # unbounded feed beside a chart strands two thirds of the row empty. And a
    # card whose body is unbound template placeholders displays its own schema
    # ("leaveTypeName / Used: used") as if it were data.
    try:
        import json as _json
        from services.dashboard_slot_fit import fit_dashboard_slots
        from services.unbound_placeholder_text import repair_unbound_templates
        for sp in Path(root, "src", "schemas").glob("**/*.json"):
            try:
                page = _json.loads(sp.read_text())
            except Exception:  # noqa: BLE001 — not every json here is a page
                continue
            if not isinstance(page, dict) or "root" not in page:
                continue
            fit = fit_dashboard_slots(page)
            ph = repair_unbound_templates(page)
            if fit["changed"] or ph["changed"]:
                sp.write_text(_json.dumps(page, indent=2))
                applied += fit["changed"] + ph["changed"]
                for note in fit["notes"] + ph["notes"]:
                    logger.info("slot_fit(%s): %s", sp.name, note)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("dashboard_slot_fit failed: %s", e)

    # A data-bound widget must be bound, in the shape it asked for. A Gauge
    # with no value draws 0 and reads as a measurement; an ActivityFeed whose
    # entity does not use its contract's field names renders "Someone" on
    # every row. Both need the registry, so this runs after it is final.
    try:
        import json as _json
        from services.widget_data_contract import reconcile_widget_data
        from services.widget_data_contract import entity_columns_from_app
        reg_path = Path(root, "contracts", "registry.json")
        registry = _json.loads(reg_path.read_text()) if reg_path.exists() else {}
        if not (registry.get("entities") or {}):
            # No registry (or an empty one) — read the columns from the app's
            # own Drizzle schema, which is where they always really are.
            registry = entity_columns_from_app(str(root))
        for sp in Path(root, "src", "schemas").glob("**/*.json"):
            try:
                page = _json.loads(sp.read_text())
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(page, dict) or "root" not in page:
                continue
            rep = reconcile_widget_data(page, registry)
            if rep["changed"]:
                sp.write_text(_json.dumps(page, indent=2))
                applied += rep["changed"]
                for note in rep["notes"]:
                    logger.info("widget_data_contract(%s): %s", sp.name, note)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("widget_data_contract failed: %s", e)

    # Everything below ran BEFORE the maquette composers until this change.
    # For any page a composer claims, the composer rewrites the schema whole,
    # so a repair computed earlier was discarded — the guard burned a pass and
    # its fix never shipped. They still do real work on pages no composer owns
    # (auth, search, custom), so they move rather than go away: one run each,
    # against final state. Relative order between them is preserved.

    # DataSource ↔ binding reconciliation: an LLM list page names its dataSource
    # off the entity plural (`recruitmentDrives`) but binds the Table's rows off
    # the route slug (`{{drives}}`), or routes a `source`/`table` at an
    # unregistered slug — either way the table renders EMPTY. Heal both the
    # rows-binding and the explicit source key against the real registered slugs.
    # Runs right after the schema/table guards so the slug set is settled.
    # Persona list pages (e.g. `carers.json` / `elderly-users.json`) often
    # bind `dataSource.entity` to `User` because the LLM reused the users
    # dataSource across pages. Rebind to the entity whose name matches the
    # page filename BEFORE the slug reconciler — otherwise the slug guard
    # sees a valid `users` slug and does nothing.
    try:
        from services.list_entity_coherence_guard import reconcile_list_entities
        lec = reconcile_list_entities(str(root))
        if lec.get("pages_rebound", 0) > 0:
            applied += lec["pages_rebound"]
            logger.info(
                "list_entity_coherence_guard: rebound %d persona list page(s) in %s: %s",
                lec["pages_rebound"],
                output_dir,
                ", ".join(f"{f} ({old}->{new})" for f, old, new in lec.get("rebound_files") or []),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("list_entity_coherence_guard skipped: %s", e)

    # Sensitive-column guard — strip password/token/secret columns from
    # every Table + DescriptionList in the app. Runs after the data-source
    # guards because they may add new Tables (list_data_source_guard,
    # widget_data_source_guard) whose columns then need the same sweep.
    # Deterministic + idempotent; conservative substring rules — see
    # ``services.sensitive_column_guard._SENSITIVE_SUBSTRINGS``.
    try:
        from services.sensitive_column_guard import strip_sensitive_columns
        sc = strip_sensitive_columns(output_dir)
        total = sc.get("table_columns_dropped", 0) + sc.get("description_items_dropped", 0)
        if total:
            applied += total
            logger.info(
                "sensitive_column_guard: dropped %d Table column(s) + %d "
                "DescriptionList item(s) across %d schema(s) in %s",
                sc.get("table_columns_dropped", 0),
                sc.get("description_items_dropped", 0),
                len(sc.get("changed") or []),
                output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("sensitive_column_guard failed: %s", e)

    # Action contract (Slice 3) — reconcile every page button/form→workflow action
    # against the REAL workflows: confirm the ref resolves, DERIVE/validate the
    # input_map (form field → real workflow input column, dropping bogus columns),
    # and set requires_record from the workflow's trigger + steps. Emits a durable
    # contracts/action-contract.json the validator/renderer can trust. Runs after
    # the button/launch-form guards so the action set is settled first.
    try:
        from services.action_contract_guard import (
            backfill_record_button_args, reconcile_action_contract,
        )
        # Complete bare record-context launcher buttons BEFORE the
        # contract reconciles, so the artifact records the repaired
        # reality (the "Reprocess → WHERE id is empty" class).
        _bf = backfill_record_button_args(str(root))
        if _bf["summary"]["buttons_patched"]:
            applied += _bf["summary"]["buttons_patched"]
            logger.info(
                "action-args backfill: wired %d record-id arg(s): %s",
                _bf["summary"]["buttons_patched"],
                ", ".join(f"{p['label']}→{p['workflow']}" for p in _bf["patched"][:5]))
        ac = reconcile_action_contract(str(root))
        if ac.get("actions"):
            logger.info(
                "action_contract_guard: reconciled %d action(s) across %d file(s) "
                "(resolved %d, unresolved %d, dropped_inputs %d) in %s",
                len(ac["actions"]), ac.get("files_scanned", 0), ac.get("resolved", 0),
                ac.get("unresolved", 0), ac.get("dropped_inputs", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("action_contract_guard failed: %s", e)

    # Detail-page actions — wire Edit/Delete on a record page to the page's OWN
    # entity + record id ({{member.id}}), not another entity's edit route with
    # {{item.id}} (Edit) or nothing at all (Delete, despite Delete<Entity> existing).
    try:
        from services.detail_action_guard import wire_detail_actions
        da = wire_detail_actions(str(root))
        if da.get("edits") or da.get("deletes"):
            applied += da.get("edits", 0) + da.get("deletes", 0)
            logger.info("detail_action_guard: wired %d Edit + %d Delete button(s) across %d page(s) in %s",
                        da.get("edits", 0), da.get("deletes", 0), da.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("detail_action_guard failed: %s", e)

    # Filter-field correctness — a metric/list filter whose value belongs to a
    # sibling field (membershipTier="Active" when Active is a status) always counts
    # 0; remap it to the field the value actually lives on (from the seed rows).
    try:
        from services.filter_field_guard import guard_filter_fields
        ff = guard_filter_fields(str(root))
        if ff.get("remapped"):
            applied += ff["remapped"]
            logger.info("filter_field_guard: remapped %d mis-fielded filter(s) across %d file(s) in %s",
                        ff["remapped"], ff.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("filter_field_guard failed: %s", e)

    # Nav route reconciliation — the sidebar links to nav-flow `pages[].route`,
    # which can drift from the page that was actually generated (a "dashboard"
    # archetype collapses two routes to /dashboard; /watchlist gets pluralised to
    # /watchlist-items). The page's schemaFile still names the REAL file, so we
    # rewrite each nav route to match its schemaFile (= the registry key) and
    # repoint post_login_redirect + the root redirect at a route that resolves.
    # Without this, every drifted nav item 404s even though the page exists.
    try:
        from services.nav_route_reconcile_guard import reconcile_nav_routes
        nr = reconcile_nav_routes(str(root))
        if nr.get("remapped") or nr.get("root_fixed"):
            applied += nr.get("remapped", 0)
            logger.info("nav_route_reconcile: remapped %d nav route(s), landing=%s, root_fixed=%s in %s",
                        nr.get("remapped", 0), nr.get("landing"), nr.get("root_fixed"), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("nav_route_reconcile_guard failed: %s", e)

    # Border coherence — strip per-node structural border overrides (radius,
    # border*) the LLM hangs on some surface containers but not others (e.g.
    # rounding "status" cards to radius.lg beside sharp KPI tiles). The design
    # register owns the border language; hand it back so every container on a
    # page shares one shape. Semantic fills + layout are preserved.
    try:
        from services.surface_border_guard import harmonize_surface_borders
        sb = harmonize_surface_borders(str(root))
        if sb.get("stripped"):
            applied += sb["stripped"]
            logger.info("surface_border_guard: stripped %d border override(s) on %d container(s) across %d file(s) in %s",
                        sb["stripped"], sb.get("nodes", 0), sb.get("files", 0), output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("surface_border_guard failed: %s", e)

    # FK dropdown targets — point every FK dropdown at the entity the SCHEMA
    # actually `.references()`, not the one guessed from the column name. `vetId`
    # and `administeredById` both reference Staff, so a name-guessed dropdown
    # bound to `vets`/`pets` (or a free-text Input feeding a uuid → the insert
    # crash) is wrong. Reads the real `.references()` map and rewrites each FK
    # Select's optionsFrom.source to the true target slug (upserting a dataSource
    # so it resolves), and promotes a uuid FK Input into a Select. Runs after the
    # earlier schema/binding + form guards and BEFORE the reference resolver, so
    # schema_references then sees a real entity and preserves the corrected source.
    try:
        from services.fk_source_guard import reconcile_fk_sources
        fs = reconcile_fk_sources(str(root))
        _fs_fixes = fs.get("fixed", 0) + fs.get("promoted", 0)
        if _fs_fixes:
            applied += _fs_fixes
            logger.info(
                "fk_source_guard: repointed %d FK dropdown source(s), promoted %d "
                "Input→Select across %d file(s) in %s",
                fs.get("fixed", 0), fs.get("promoted", 0), fs.get("files", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("fk_source_guard failed: %s", e)

    # READ-BINDING CONTRACT — the final read-binding pass, after every page-emitting
    # and renaming pass has settled. `reconcile_list_sources` above only heals
    # Table `rows`/`items` naming drift; it cannot help a Chart/map/Stat bound to a
    # dangling name, nor a DERIVED widget (`{{activeRecruitmentDrives}}`,
    # `{{recentApplicants}}`) whose filtered dataSource was never declared. This
    # reconciler covers the full read surface (rows/items/data/resources/events/
    # entries/dotted value) and MATERIALIZES the missing dataSource — decoding the
    # semantic prefix (active/recent/upcoming/…) into a real filter/sort/limit over
    # the entity's actual columns — so the binding resolves instead of rendering
    # empty. Writes contracts/data-contract.json. Additive + idempotent.
    try:
        from services.read_binding_guard import reconcile_read_bindings
        rb = reconcile_read_bindings(str(root))
        _by = rb.get("actions_by_kind", {})
        _rb_fixed = _by.get("remapped", 0) + _by.get("materialized", 0)
        if _rb_fixed:
            applied += _rb_fixed
        if _rb_fixed or _by.get("unresolved"):
            logger.info(
                "read_binding_guard: %s across %d file(s) in %s",
                _by, rb.get("files_changed", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("read_binding_guard failed: %s", e)

    # Aggregate metrics — an op:"aggregate" dataSource authored with NO
    # `metrics` block (or an incomplete one) means every `{{S.key}}` binding
    # resolves to undefined at runtime and blanks the KPI tile. Walk each page,
    # collect the referenced keys per aggregate source, and inject
    # `{fn:"sum", field:<col>}` when the entity has a matching numeric column.
    # Diagnostics for any key without a numeric backing column — never
    # silently dropped. Runs AFTER read_binding_guard so any aggregate source
    # that pass materialized is swept too. Idempotent; strict under
    # FORGE_BINDING_GATE (ERROR-level), warn-only otherwise.
    try:
        from services.aggregate_metrics_guard import guard_aggregate_metrics
        am = guard_aggregate_metrics(str(root))
        if am.get("injected"):
            applied += am["injected"]
            logger.info(
                "aggregate_metrics_guard: injected %d metric(s) across %d file(s) in %s",
                am["injected"], am.get("files_changed", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("aggregate_metrics_guard failed: %s", e)

    # NOTE: a second sensitive-column sweep used to sit here. It existed
    # because the composers re-authored columns from a registry that still
    # contained ``passwordHash`` / ``resetToken``, undoing the earlier sweep.
    # Both causes are gone: the sweep above now runs AFTER the composers, and
    # ``strip_sensitive_from_registry`` cleans the composers' input so they
    # cannot emit a sensitive column in the first place. Running the guard
    # twice was laundering a bad input, not defence in depth.

    try:
        from services.dashboard_completeness import apply_dashboard_completeness
        dc = apply_dashboard_completeness(str(root))
        if dc.get("sections_added"):
            applied += int(dc["sections_added"])
            logger.info(
                "dashboard_completeness: added %d section(s) across %d page(s) in %s: %s",
                dc["sections_added"], len(dc.get("pages_touched", [])),
                output_dir, ", ".join(dc.get("pages_touched", [])),
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("dashboard_completeness failed: %s", e)

    # Bare-container guard — surfaces with no children or heading-only stop
    # feeling like blank space. Prunes truly-empty containers; on a
    # heading-only Card/Section, appends a subtle EmptyState so the surface
    # reads as intentional. Targeted fix for the "blank spaces" symptom of
    # B-022.5 across every generated app. Runs after dashboard_completeness
    # so the added sections aren't retroactively pruned.
    try:
        from services.bare_container_guard import apply_bare_container_guard
        bc = apply_bare_container_guard(str(root))
        _bc = int(bc.get("empty_removed", 0)) + int(bc.get("empty_states_added", 0))
        if _bc:
            applied += _bc
            logger.info(
                "bare_container_guard: pruned=%d empty_states_added=%d across %d file(s) in %s",
                bc.get("empty_removed", 0), bc.get("empty_states_added", 0),
                len(bc.get("files_touched", [])), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("bare_container_guard failed: %s", e)

    # Route-intent application — pages whose route semantically means
    # something more specific than "CRUD X" (profile/settings/account =
    # singleton_current_user; my-recipes/my-orders = current_user_scope_list;
    # home-cooks/reviewers = role_scope_list) get restructured so the
    # dataSource carries the correct filter or the page collapses to a
    # currentUser-bound form. Root-cause fix for B-022.6 (/profile → Add
    # User leak), B-022.7 (Home cooks shows irrelevant data), and B-022.9
    # (My recipes shows all recipes / new entries don't appear). Structural,
    # additive, idempotent — ordinary CRUD paths are untouched.
    try:
        from services.route_intent_apply import apply_route_intent
        ri = apply_route_intent(str(root))
        _ri_edits = int(ri.get("singleton_pages", 0)) + int(ri.get("user_scope_lists", 0)) + int(ri.get("role_scope_lists", 0))
        if _ri_edits:
            applied += _ri_edits
            logger.info(
                "route_intent_apply: singleton=%d user_scoped=%d role_scoped=%d across %d file(s) in %s",
                ri.get("singleton_pages", 0), ri.get("user_scope_lists", 0),
                ri.get("role_scope_lists", 0), len(ri.get("files_touched", [])), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("route_intent_apply failed: %s", e)

    # Navigate-target existence guard — every button/link `navigate` prop
    # must resolve to a real plan route. LLM-authored schemas frequently
    # emit navigate values pointing at routes that never got generated
    # (B-022.8's dead "View details" buttons class). Repairs to the nearest
    # matching prefix when one exists; otherwise marks the node with
    # `data-nav-warn="broken"` so the layout stays intact but the mismatch
    # is observable. Deterministic + idempotent + additive.
    try:
        from services.navigate_target_guard import apply_navigate_target_guard
        nt = apply_navigate_target_guard(str(root))
        _nt_edits = len(nt.get("repaired", [])) + len(nt.get("marked", []))
        if _nt_edits:
            applied += _nt_edits
            logger.info(
                "navigate_target_guard: repaired=%d marked=%d across %d file(s) in %s",
                len(nt.get("repaired", [])), len(nt.get("marked", [])),
                len(nt.get("files_touched", [])), output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("navigate_target_guard failed: %s", e)

    # Text-template backstop — the LLM authors mechanical strings (empty
    # states like "No plant batchs yet.", standard button labels) inside JSON
    # schemas with fractional attention per string, so plural typos (-ch → s
    # instead of -es) and phrasing drift are common. Overwrite every
    # mechanical string with the deterministic value computed from the
    # entity name (services.text_templates). Idempotent, never touches
    # domain-authored strings (helperText, description, custom empty states).
    # Runs late so any earlier guard that regenerated a schema has been
    # committed.
    try:
        from services.text_template_backstop import apply_text_template_backstop
        tb = apply_text_template_backstop(str(root))
        if tb.get("files_touched"):
            applied += len(tb["files_touched"])
            logger.info(
                "text_template_backstop: normalised %d schema file(s) in %s: %s",
                len(tb["files_touched"]), output_dir, ", ".join(tb["files_touched"]),
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("text_template_backstop failed: %s", e)

    # Commerce placement — for every plan entity flagged commerce:true (see
    # services.commerce_flag), drop AddToCart into its list/detail schema,
    # emit /cart backed by CartPage, and inject a CartBadge into the shell.
    # No-op when no commerce entities are present. Runs late so the schemas
    # it edits are the final ones, and BEFORE token_completeness_guard so any
    # subtree it touches still gets its backfill pass.
    try:
        from services.commerce_placement import apply_commerce_placement
        cp = apply_commerce_placement(str(root))
        _cp_touched = int(cp.get("list_edits", 0)) + int(cp.get("detail_edits", 0)) \
            + int(bool(cp.get("cart_page_created"))) + int(bool(cp.get("cart_in_plan"))) \
            + int(bool(cp.get("shell_badge")))
        if _cp_touched:
            applied += _cp_touched
            logger.info(
                "commerce_placement: entities=%s list_edits=%d detail_edits=%d "
                "cart_page_created=%s cart_in_plan=%s shell_badge=%s (in %s)",
                cp.get("entities"), cp.get("list_edits", 0), cp.get("detail_edits", 0),
                cp.get("cart_page_created"), cp.get("cart_in_plan"), cp.get("shell_badge"),
                output_dir,
            )
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("commerce_placement failed: %s", e)

    # Token completeness — refill design-spec / tokens.custom subtrees the
    # library reads unconditionally (typography.numeric, spacing.semantic, …).
    # Missing subtrees crash SSR with "An error occurred in the Server
    # Components render" — the B-020.8 symptom class. Runs last so any
    # earlier guard that rewrote design-spec is already committed.
    try:
        from services.token_completeness_guard import apply_token_completeness_guard
        tc = apply_token_completeness_guard(str(root))
        if tc.get("total_keys_added", 0) > 0:
            logger.info(
                "token_completeness_guard: backfilled %d key(s) across %d file(s) in %s: %s",
                tc["total_keys_added"], len(tc["files_touched"]), output_dir,
                ", ".join(tc["files_touched"]),
            )
            applied += tc["total_keys_added"]
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("token_completeness_guard failed: %s", e)

    # Platform heals — deterministic in-place repair of known regression
    # classes (cwx1stzz 2026-08-21 session): destructive skin CSS that
    # force-collapses KPI grids, missing Tailwind grid-cols safelist,
    # invented filter-enum options that can never match a row, sub-floor
    # dashboard rhythm, drifted template-owned runtime files. All heals are
    # idempotent — a fresh generation reports zero changes for most of them.
    try:
        from services.platform_heals import apply_platform_heals
        ph = apply_platform_heals(str(root))
        if ph.get("changed"):
            logger.info("platform_heals applied on %s: %s", output_dir, ph)
            applied += 1
    except Exception as e:  # noqa: BLE001 — never block generation on heals
        logger.warning("platform_heals failed: %s", e)

    # MOBILE-A — emit the Expo mobile shell (App.tsx WebView + eas.json + icons)
    # into every generated app. Idempotent; safe on re-runs. The deployed URL
    # isn't known at first-gen time — Publish flow re-invokes this later with
    # the URL populated (Slice C wires that). Failure is non-fatal: mobile is
    # additive, so we log and move on rather than blocking web generation.
    try:
        from services.mobile_scaffold import scaffold_mobile
        result = scaffold_mobile(str(root))
        logger.info(
            "mobile_scaffold: wrote %d files to %s/mobile (app=%r)",
            len(result["files_written"]), output_dir, result["app_name"],
        )
        applied += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("mobile_scaffold failed: %s", e)

    # JV-15c — Docker artifacts for the verify runner (Dockerfile.verify +
    # docker-compose.verify.yml + .dockerignore). Idempotent; regenerated
    # per build so template improvements propagate without needing users
    # to blow away their app. Non-fatal — Docker being unavailable just
    # means Verify & Fix falls back to host-mode boot (JV-2).
    try:
        from services.emit_verify_container import (
            emit_verify_container_artifacts,
        )
        res = emit_verify_container_artifacts(str(root))
        if not res.get("skipped"):
            logger.info(
                "emit_verify_container: wrote %s in %s",
                res.get("written"), output_dir,
            )
            applied += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("emit_verify_container failed: %s", e)

    # MOBILE-E — replace placeholder icons + emit store-listing draft. Runs
    # AFTER mobile_scaffold so app.json is present and honors its resolved
    # name / brand color. Non-fatal like the scaffold pass; if Pillow is
    # missing or drawing fails, the solid-color placeholders stay in place.
    try:
        from services.mobile_branding import apply_mobile_branding
        branding = apply_mobile_branding(str(root / "mobile"))
        if branding.get("applied"):
            logger.info(
                "mobile_branding: wrote %d files (monogram=%r, brand=%s)",
                len(branding.get("files_written", [])),
                branding.get("monogram"),
                branding.get("brand_hex"),
            )
            applied += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("mobile_branding failed: %s", e)

    # WORKFLOW GRAPH GATE — reachability, dangling edges, missing terminal,
    # unknown action types — with auto-repair against the node contract.
    #
    # This pass existed only inside the fresh-generation ROUTE
    # (routers/generate.py), so the guard suite that Smith's orchestrator runs
    # after every edit never invoked it (register S22-2/S21-2): a workflow left
    # with a dangling edge by an edit passed the whole suite green. Running it
    # here puts it on every path, and reporting each repair at WARNING means
    # `GuardResult` NAMES what was rewritten — a silent rewrite of authored
    # content is indistinguishable from the edit never having been saved.
    #
    # Idempotent, so the route's own plan-aware call remains harmless.
    try:
        from services.workflow_graph_gate import run_workflow_gate
        gate = run_workflow_gate(output_dir)
        if gate.get("repaired"):
            for wf_name, report in (gate.get("reports") or {}).items():
                if not isinstance(report, dict):
                    continue
                changes = list(report.get("fixed") or [])
                changes += [str(c) for c in (report.get("value_type_fixes") or [])]
                if changes:
                    logger.warning(
                        "workflow_graph_gate: rewrote workflows/%s — %s",
                        wf_name, "; ".join(str(c) for c in changes),
                    )
            applied += int(gate["repaired"])
        if gate.get("warnings"):
            logger.warning(
                "workflow_graph_gate: %d warning(s) across %d workflow(s) in %s",
                gate["warnings"], gate.get("checked", 0), output_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.error("workflow_graph_gate failed in the guard suite: %s", e)

    # Spec E Wave 1 — advanced-interactions passes. Both flag-gated on
    # FORGE_E_INTERACTIONS; both no-op when off. Order matters:
    # interaction_authority strips invalid `reorderable/bulkActions/
    # moveBetweenLanes` first, then reorder_column_pass adds the
    # sortOrder column + reorder route for whatever survives.
    try:
        from services import interaction_authority as _ia
        if _ia.is_enabled():
            _ia_report = _ia.validate_output_dir(str(root))
            _ia.persist_report(_ia_report, str(root))
            if _ia_report.files_written:
                applied += _ia_report.files_written
                logger.info(
                    "interaction_authority: sanitised %d file(s), %d finding(s) in %s",
                    _ia_report.files_written, len(_ia_report.findings), output_dir,
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("interaction_authority failed: %s", e)

    try:
        from services import reorder_column_pass as _rcp
        if _rcp.is_enabled():
            _rcp_report = _rcp.run(str(root))
            if _rcp_report["schema_files_patched"] or _rcp_report["route_copied"]:
                applied += len(_rcp_report["schema_files_patched"])
                if _rcp_report["route_copied"]:
                    applied += 1
                logger.info(
                    "reorder_column_pass: patched %d schema file(s), route_copied=%s in %s",
                    len(_rcp_report["schema_files_patched"]),
                    _rcp_report["route_copied"], output_dir,
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("reorder_column_pass failed: %s", e)

    # Spec E Wave 3 — advanced UX patterns. Each pass is flag-gated on
    # FORGE_E_PATTERNS and no-ops when off. Order matters:
    #   wizard_page_pass    swaps form pages that declared page.wizard
    #                       for a Wizard component (must run before the
    #                       filter builder so a wizardified page isn't
    #                       accidentally targeted for a filter chip);
    #   filter_builder_pass injects FilterBuilder above the Table when
    #                       page.list.filter_fields is declared;
    #   onboarding_tour_pass emits the tour JSON + wires TourOverlay
    #                       into the shell (once per app, not per page).
    try:
        from services import wizard_page_pass as _wpp
        if _wpp.is_enabled():
            _wpp_report = _wpp.run(str(root))
            if _wpp_report.get("pages_touched"):
                applied += len(_wpp_report["pages_touched"])
                logger.info(
                    "wizard_page_pass: applied to %d page(s) in %s",
                    len(_wpp_report["pages_touched"]), output_dir,
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("wizard_page_pass failed: %s", e)

    try:
        from services import filter_builder_pass as _fbp
        if _fbp.is_enabled():
            _fbp_report = _fbp.run(str(root))
            if _fbp_report.get("pages_touched"):
                applied += len(_fbp_report["pages_touched"])
                logger.info(
                    "filter_builder_pass: applied to %d page(s) in %s",
                    len(_fbp_report["pages_touched"]), output_dir,
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("filter_builder_pass failed: %s", e)

    try:
        from services import onboarding_tour_pass as _otp
        if _otp.is_enabled():
            _otp_report = _otp.run(str(root))
            if _otp_report.get("steps", 0) > 0 and _otp_report.get("config_written"):
                applied += 1
                logger.info(
                    "onboarding_tour_pass: %d step(s), shells_patched=%s in %s",
                    _otp_report["steps"], _otp_report.get("shells_patched"), output_dir,
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("onboarding_tour_pass failed: %s", e)

    next_dir = root / ".next"
    if next_dir.exists():
        try:
            shutil.rmtree(next_dir)
            logger.info("Cleared stale .next build cache in %s", output_dir)
            applied += 1
        except OSError as e:
            logger.warning("Could not clear .next cache: %s", e)

    # PIPELINE VALIDATORS — the deterministic Layer 2/3/4 modules from
    # docs/superpowers/plans/2026-08-04-generation-pipeline-remediation.md.
    # Each runs best-effort; findings persist to contracts/ and are picked up
    # by the frontend chip. Failures never block generation — the report itself
    # is the surface.
    #
    # workflow_validator: undefined `{{refs}}`, SQL literals as values,
    #   event-status-not-written (using LockedSpec if present).
    # contract_validator: pages/actions/bindings vs the manifest.
    # proof_pass: aggregates the above + four page-quality checks.
    # Final workflow-variable reconcile — MUST run after every workflow
    # mutator (sync, graph gate, persist wiring) and before the validator,
    # so refs introduced late are declared/repaired instead of flagged.
    try:
        from services.workflow_variable_reconcile import (
            reconcile_workflow_variables,
        )
        _wvr = reconcile_workflow_variables(root)
        if _wvr.get("files"):
            logger.info("[wf-var-reconcile] reconciled %d workflow file(s)",
                        len(_wvr["files"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow variable reconcile failed: %s", exc)

    try:
        from services.workflow_validator import (
            persist_report as _persist_wfv,
            validate_output_dir as _run_wfv,
        )
        _wfv_findings = _run_wfv(str(root))
        if _wfv_findings:
            _persist_wfv(_wfv_findings, str(root))
            logger.info("workflow_validator: %d finding(s) in %s", len(_wfv_findings), output_dir)
    except Exception as exc:  # noqa: BLE001 — never block generation
        logger.warning("workflow_validator failed: %s", exc)

    try:
        from services.contract_validator import (
            persist_report as _persist_cv,
            validate_output_dir as _run_cv,
        )
        _cv_findings = _run_cv(str(root))
        if _cv_findings:
            _persist_cv(_cv_findings, str(root))
            logger.info("contract_validator: %d finding(s) in %s", len(_cv_findings), output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("contract_validator failed: %s", exc)

    try:
        from services.proof_pass import persist_report as _persist_pp, run_proof_pass
        report = run_proof_pass(str(root))
        _persist_pp(report, str(root))
        logger.info(
            "proof_pass: passed=%s errors=%d warnings=%d in %s",
            report.passed, report.error_count, report.warning_count, output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("proof_pass failed: %s", exc)

    # RTL scope — the design agent writes `direction: rtl` on html/body for
    # any app with a non-Latin name, but layout.tsx emits lang="en" with no
    # `dir` and the copy is English, so LTR text renders mirrored. Scope the
    # rules to [dir="rtl"] so they apply when the document says so.
    try:
        from services.rtl_scope_guard import apply_rtl_scope_guard
        _rtl = apply_rtl_scope_guard(root)
        if _rtl.get("scoped"):
            logger.info("rtl_scope_guard: scoped %d rule(s) in %s",
                        _rtl["scoped"], output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rtl_scope_guard failed: %s", exc)

    # Rules-engine validator — sweeps src/rules for LLM-fabricated entities/
    # fields/workflow refs. Additive; writes contracts/rules_validation.json.
    try:
        from services.rules_validator import (
            persist_report as _persist_rv,
            validate_output_dir as _run_rv,
        )
        _rv_findings = _run_rv(str(root))
        if _rv_findings:
            _persist_rv(_rv_findings, str(root))
            logger.info("rules_validator: %d finding(s) in %s", len(_rv_findings), output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rules_validator failed: %s", exc)

    # Proof-report auto-heal — closes the loop between validation and repair.
    # Deterministic fixers for the failure classes we can safely mechanize:
    # SQL literals as values, {{now}}/{{today}} refs, missing workflow trigger
    # nodes, and orphan navigate targets within edit distance of a real route.
    # Re-runs proof_pass after each iteration and stops when it converges or
    # no more fixes apply. Whatever remains is genuinely LLM-territory and
    # gets left for Smith or the frontend chip to surface.
    try:
        from services.proof_auto_heal import persist_heal_report, run_auto_heal
        _heal = run_auto_heal(str(root))
        if _heal.iterations > 0:
            persist_heal_report(_heal, str(root))
            logger.info(
                "proof_auto_heal: %d iteration(s), converged=%s, "
                "fixes=%s, remaining errors=%d warnings=%d",
                _heal.iterations, _heal.converged,
                dict(_heal.fixes_by_type),
                _heal.remaining_errors, _heal.remaining_warnings,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("proof_auto_heal failed: %s", exc)

    # Playwright verify auto-trigger — reads proof_report and dispatches
    # the existing runner if it exists AND proof failed. Fire-and-forget;
    # never blocks or raises.
    try:
        from services.verify_trigger import trigger_verify
        _vresult = trigger_verify(str(root))
        if _vresult.get("dispatched"):
            logger.info("verify_trigger: dispatched via %s", _vresult.get("runner"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_trigger failed: %s", exc)

    # Archetype-owned page rewrites. Idempotent: only fires when the plan's
    # archetype is registered AND the page hasn't already been brought to
    # the archetype's canonical shape. Motivating case:
    # visual-product-search /scan is authored as a static dashboard by the
    # LLM, so clicking the workflow button dispatches with empty inputs
    # and the "imageUrl required" rule aborts. This rewrite replaces
    # /scan with the stateful poll+Conditional+Form pattern.
    try:
        from services.archetype_page_fixes import (
            rewrite_scan_page_for_visual_product_search,
        )
        _apf = rewrite_scan_page_for_visual_product_search(str(root))
        if _apf:
            applied += _apf
    except Exception as exc:  # noqa: BLE001
        logger.warning("archetype_page_fixes failed: %s", exc)

    # Results-page guarantee (visual-product-search): /<scans>/[id]/results
    # exists as the proven product-card grid (offer image, retailer + price,
    # store link) with Back/Scan Another nav and confirm/discard actions.
    try:
        from services.archetype_page_fixes import (
            ensure_results_page_for_visual_product_search,
        )
        _arp = ensure_results_page_for_visual_product_search(str(root))
        if _arp:
            applied += _arp
    except Exception as exc:  # noqa: BLE001
        logger.warning("results-page emitter failed: %s", exc)

    # Barcode capability wiring (visual-product-search): scan/landing pages
    # get the auto-submitting BarcodeScanner card, history gets thumbnails,
    # and detail-scoped offer lists get the $routeId session filter. All
    # id-guarded — safe on every re-run. LensShop back-port (2026-08-19).
    try:
        from services.archetype_page_fixes import add_barcode_capabilities
        _abc = add_barcode_capabilities(str(root))
        if _abc:
            applied += _abc
            logger.info("barcode capabilities wired: %d file(s)", _abc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("barcode capability wiring failed: %s", exc)

    # Per-app BLUEPRINT.md — deterministic Markdown snapshot of the whole
    # app, always current. Wired here so every generation ends with a
    # fresh blueprint on disk without generation code needing to know.
    # Flag-gated + fail-safe: an error here NEVER breaks generation.
    try:
        from services.blueprint_writer import write_blueprint_safe
        write_blueprint_safe(
            str(root),
            source="generation",
            summary=f"Full generation ({applied} guard(s) applied)",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("blueprint_writer failed: %s", exc)

    # Sprint 10 — roll every per-page critic report up into a single
    # summary.json so a human/Smith can read the design signal without
    # opening 20 files. No-op when the critic didn't run (no reports).
    try:
        from services.page_critic_summary import persist_summary
        p = persist_summary(str(root))
        if p is not None:
            logger.info("[critic-summary] wrote %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("page_critic_summary failed: %s", exc)

    # IRF substrate — load plan.json once, then run the three flag-gated
    # M6 passes that depend on the picked aesthetic profile and shape.
    # Order matters: pick FIRST (surface_treatment reads the picked name),
    # then paint, then form UX. Each pass is idempotent + self-flag-gated
    # + fail-safe (guarded with the same "never block generation" pattern
    # as everything above).
    _irf_plan: dict = {}
    _picked_profile: str | None = None
    try:
        # Canonical location in generated apps is src/contracts/plan.json;
        # the two shorter paths are historical fallbacks (older layouts +
        # synthetic test fixtures).
        _irf_plan_path = None
        for _cand in (
            root / "src" / "contracts" / "plan.json",
            root / "contracts" / "plan.json",
            root / "plan.json",
        ):
            if _cand.exists():
                _irf_plan_path = _cand
                break
        if _irf_plan_path is not None:
            import json as _json
            _irf_plan = _json.loads(_irf_plan_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("irf: plan.json load failed: %s", exc)

    # M6-T3 — pick the aesthetic profile once. Always runs (picker is
    # deterministic + returns a default). Stashed for the surface pass +
    # substrate brief.
    try:
        from services.aesthetic_profile_picker import pick as _pick_profile
        from services.design_brief_to_prompt import load_brief_from_disk as _load_brief
        _brief_for_pick = None
        try:
            _brief_for_pick = _load_brief(root)
        except Exception:  # noqa: BLE001
            # Brief-load is best-effort; a missing/malformed brief.json
            # just means the veto layer has no signal to reject on.
            _brief_for_pick = None
        _picked_profile = _pick_profile(_irf_plan, brief=_brief_for_pick)
        logger.info("[irf-aesthetic] picked profile: %s", _picked_profile)
    except Exception as exc:  # noqa: BLE001
        logger.warning("aesthetic_profile_picker failed: %s", exc)

    # M6-T4 — post-gen aesthetic paint pass. Flag-gated inside the
    # module (FORGE_SURFACE_TREATMENT). Idempotent + profile-swap safe.
    try:
        from services.surface_treatment_pass import apply as _apply_surface
        _sr = _apply_surface(str(root), _irf_plan)
        if isinstance(_sr, dict) and _sr.get("applied"):
            applied += int(_sr.get("applied") or 0)
            logger.info(
                "[irf-surface] profile=%s schemas_touched=%s changes=%s",
                _sr.get("profile"), _sr.get("schemas_touched"), _sr.get("applied"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("surface_treatment_pass failed: %s", exc)

    # M6-T6 — form UX invariants (30 rules: 15 auto-fixes, 15 findings).
    # Flag-gated inside the module (FORGE_FORM_UX_INVARIANTS).
    try:
        from services.form_ux_invariants import apply as _apply_form_ux
        _fx = _apply_form_ux(str(root), _irf_plan)
        if isinstance(_fx, dict):
            _fx_applied = int(_fx.get("applied") or 0)
            _fx_findings = len(_fx.get("findings") or [])
            if _fx_applied or _fx_findings:
                applied += _fx_applied
                logger.info(
                    "[irf-form-ux] auto-fixed=%d findings=%d",
                    _fx_applied, _fx_findings,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("form_ux_invariants failed: %s", exc)

    # M7-T3 — emit one substrate-brief JSONL row so the /quality dashboard
    # sees this generation. Always runs (dashboard-only observability).
    try:
        from services.substrate_brief_writer import emit_brief as _emit_brief
        _bp = _emit_brief(
            str(root),
            project_id=None,
            aesthetic_profile=_picked_profile,
            # coverage_verdict + guards_fired: pipeline may enrich later; a
            # bare row is still useful.
        )
        if _bp is not None:
            logger.info("[irf-brief] wrote %s", _bp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("substrate_brief_writer failed: %s", exc)

    # ── QUALITY TAIL — must stay the LAST thing this function does. ──
    # Everything above (including page_composer / record_maquette LLM
    # re-composition and proof/irf passes) can rewrite page schemas;
    # these passes repair + judge the FINAL state. atb0m97x shipped
    # un-gated because this tail ran mid-file. Do not add passes below
    # the delivery gate.
    # Route dedup (F3, item 4) — one user job, one route. Collapses
    # job-equivalent duplicates (two create surfaces for the same
    # entity, two search screens) into a canonical winner + Redirect
    # aliases, and removes duplicate /api/**/search endpoints. Runs
    # BEFORE the materializer/gate so they see the canonical route set.
    try:
        from services.route_dedup import (
            dedupe_routes,
            dedupe_schema_files,
            dedupe_search_endpoints,
        )
        _sfd = dedupe_schema_files(root)
        if _sfd.get("removed"):
            logger.info("[schema-dedup] removed %d duplicate-route file(s)",
                        len(_sfd["removed"]))
        _rd = dedupe_routes(str(root))
        if _rd.get("collapsed"):
            applied += len(_rd["collapsed"])
            logger.info("route-dedup: collapsed %d duplicate route(s)",
                        len(_rd["collapsed"]))
        _se = dedupe_search_endpoints(str(root))
        if _se.get("removed"):
            applied += len(_se["removed"])
    except Exception as e:  # noqa: BLE001
        logger.warning("route dedup failed: %s", e)

    # Density frames (G5, item 4) — sparse pages (lone form, no wide
    # widgets) get a centered narrow column; density stamped on every
    # page doc for downstream composers.
    try:
        from services.density_frames import apply_density_frames
        _df = apply_density_frames(str(root))
        if _df.get("framed"):
            applied += len(_df["framed"])
    except Exception as e:  # noqa: BLE001
        logger.warning("density frames failed: %s", e)

    # Page-anatomy contracts (item 5) — the per-kind UX floor: detail
    # pages get a back affordance, list pages get their create button
    # when the create route exists, search results declare a no-match
    # state; missing primary actions are reported (planner judgment,
    # never invented). Additive + idempotent.
    try:
        from services.page_anatomy import apply_page_anatomy
        _pa = apply_page_anatomy(str(root))
        if _pa["summary"].get("injected"):
            applied += _pa["summary"]["injected"]
    except Exception as e:  # noqa: BLE001
        logger.warning("page anatomy failed: %s", e)

    # Page-level navigation — breadcrumbs on nested pages. Runs after
    # anatomy so the back affordance is already in place and the crumb
    # sits above it. Crumb hrefs come from the route tree, so they only
    # ever point at routes that exist. Additive + idempotent; an
    # authored Breadcrumb is never rewritten.
    try:
        from services.page_nav import apply_page_nav
        _pn = apply_page_nav(str(root))
        if _pn["summary"].get("breadcrumbs_injected"):
            applied += _pn["summary"]["breadcrumbs_injected"]
    except Exception as e:  # noqa: BLE001
        logger.warning("page nav failed: %s", e)

    # Ship the route hierarchy so the running shell can render crumbs for
    # the ~300 nested routes that are hand-written .tsx (no schema to
    # patch). Written AFTER apply_page_nav so `owned_by_schema` reflects
    # the crumbs just injected and the shell never doubles up.
    try:
        from services.page_nav import write_route_tree_contract
        write_route_tree_contract(str(root))
    except Exception as e:  # noqa: BLE001
        logger.warning("route-tree contract failed: %s", e)

    # Transition materializer (B1+B2) — inject the UI the contracts
    # promised, right before the gate judges: buttons for nav-flow
    # ``button:<Label>`` transitions the page schema lacks, and dispatch
    # buttons for plan workflows triggered by "button on <Page>" whose
    # workflow exists on disk. Runs immediately BEFORE the delivery gate
    # so strict mode converges instead of failing on repairable misses;
    # unrepairable ones (workflow never emitted) are deliberately left
    # for the gate to report.
    try:
        from services.transition_materializer import run as _materialize
        _mat = _materialize(str(root))
        _mt = len(_mat["transitions"].get("injected") or [])
        _ml = len(_mat["workflow_launchers"].get("injected") or [])
        if _mt or _ml:
            applied += _mt + _ml
            logger.info(
                "transition-materializer: injected %d transition button(s), "
                "%d workflow launcher(s)", _mt, _ml,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("transition materializer failed: %s", e)


    # Binding-prop normalizer — composer/LLM `props.dataSource:"name"`
    # becomes the renderer's canonical binding (Table.rows /
    # ActivityFeed.entries / Chart.data = "{{name}}"); DescriptionList
    # bare names get wrapped; bare Selects get enum options backfilled
    # from plan enum_values. Runs before binding_smoke so the smoke
    # check judges the normalized (renderable) spelling.
    try:
        from services.binding_prop_normalizer import normalize_binding_props
        _bn = normalize_binding_props(str(root))
        _bns = _bn["summary"]
        if _bns["normalized"] or _bns["selects_filled"]:
            applied += _bns["normalized"] + _bns["selects_filled"]
            logger.info(
                "binding-normalize: %d binding(s) canonicalized, "
                "%d select(s) backfilled, %d unresolved",
                _bns["normalized"], _bns["selects_filled"],
                _bns["unresolved"])
    except Exception as e:  # noqa: BLE001
        logger.warning("binding-prop normalizer failed: %s", e)

    # File-preview guard — raw bound-iframe CustomBlocks become the
    # reference app's <object type="application/pdf"> pattern (via the
    # /api/files/preview route when the app ships it). An object shows
    # its inline fallback on a bogus/empty file path; a raw iframe
    # renders the APP inside itself (atb0m97x recursive-preview class).
    try:
        from services.file_preview_guard import apply_file_preview_guard
        _fp = apply_file_preview_guard(str(root))
        if _fp["summary"]["rewritten"]:
            applied += _fp["summary"]["rewritten"]
            logger.info("file-preview guard: rewrote %d preview block(s)",
                        _fp["summary"]["rewritten"])
    except Exception as e:  # noqa: BLE001
        logger.warning("file-preview guard failed: %s", e)

    # Rules sanity — deactivate computed rules that read AND overwrite
    # their own field with string literals (tier-into-score class):
    # they corrupt the column and make the companion range validation
    # reject every insert, so the trigger form can never create a row.
    try:
        from services.rules_sanity import sanitize_rules
        _rs = sanitize_rules(str(root))
        if _rs["summary"]["deactivated"]:
            applied += _rs["summary"]["deactivated"]
            logger.info("rules-sanity: deactivated %d self-clobbering rule(s): %s",
                        _rs["summary"]["deactivated"], _rs["deactivated"])
    except Exception as e:  # noqa: BLE001
        logger.warning("rules sanity failed: %s", e)

    # Page-contract gate — judge every page against the SAME contract
    # the renderer enforces (component-contracts.json + built-in node
    # set): unknown types, missing required props, unbound Tables, bare
    # Selects, bound iframes. A gate CHECK, not a guard: repairs
    # nothing, so upstream producers get fixed instead of masked.
    # FORGE_PAGE_CONTRACT_GATE=off|warn|strict (default warn); strict
    # raises. Runs after all repairs so it judges the shipped state.
    # Deterministic required-prop backfills (Hero.headline/layout,
    # EmptyState.message, Select.options) BEFORE the gate, so the gate
    # judges what actually ships instead of flagging repairable holes.
    try:
        from services.page_contract_repair import repair_required_props
        _pcr = repair_required_props(root)
        if _pcr.get("repaired"):
            logger.info("[page-contract-repair] backfilled required props on %d page(s)",
                        len(_pcr["repaired"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("page-contract repair failed to run: %s", e)

    _pc_mode = os.environ.get("FORGE_PAGE_CONTRACT_GATE", "warn").lower()
    if _pc_mode != "off":
        try:
            import json as _pc_json

            from services.page_contract_validator import validate_pages
            _pc = validate_pages(str(root))
            try:
                _pc_dir = root / "contracts"
                _pc_dir.mkdir(parents=True, exist_ok=True)
                (_pc_dir / "page-contract.json").write_text(
                    _pc_json.dumps(_pc, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            if _pc["summary"]["errors"]:
                logger.warning(
                    "page-contract: %d violation(s) across %d page(s) "
                    "(see contracts/page-contract.json)",
                    _pc["summary"]["errors"], _pc["summary"]["pages"])
                if _pc_mode == "strict":
                    raise RuntimeError(
                        f"page-contract gate: {_pc['summary']['errors']} "
                        "violation(s) — pages break the renderer contract")
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("page-contract gate failed to run: %s", e)

    # Binding smoke (F2) — would any binding-backed container render
    # EMPTY on first boot? Checks every page dataSource against the seed
    # plan (rows exist + survive simple eq-filters). Runs after all
    # repairs, before the gate. FORGE_BINDING_SMOKE=off|warn|strict
    # (default warn); strict raises — same contract as the gate.
    try:
        from services.binding_smoke import BindingSmokeError, run_binding_smoke
    except Exception as e:  # noqa: BLE001
        logger.warning("binding smoke unavailable: %s", e)
    else:
        try:
            _bs = run_binding_smoke(str(root))
            if _bs["summary"].get("error"):
                logger.warning(
                    "binding-smoke: %d empty binding(s) (see binding-smoke.json)",
                    _bs["summary"]["error"],
                )
        except BindingSmokeError:
            raise  # strict mode — empty first paint fails the build
        except Exception as e:  # noqa: BLE001
            logger.warning("binding smoke failed to run: %s", e)

    # RT-3 — junk create pages. Remove create forms scaffolded under
    # non-entity stems (/home/new — a "create" for the dashboard) before
    # the menu sync + gate read the route set.
    try:
        from services.ensure_edit_routes import remove_junk_create_pages
        _jc = remove_junk_create_pages(str(root))
        if _jc["removed"]:
            applied += len(_jc["removed"])
            logger.info("junk-create-pages: removed %s", ", ".join(_jc["removed"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("remove_junk_create_pages failed: %s", e)

    # RT-6 — aggregate-root workspace tabs. Detail pages whose route has
    # static nested children (/events/[id]/sessions…) get a tab-link row
    # so the child workspaces are reachable in the UI, not just by URL.
    try:
        from services.record_subresource_tabs import inject_subresource_tabs
        _st = inject_subresource_tabs(str(root))
        if _st["pages"]:
            applied += len(_st["pages"])
            logger.info("subresource-tabs: %d tab(s) on %s",
                        _st["tabs"], ", ".join(_st["pages"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("inject_subresource_tabs failed: %s", e)

    # RT-1/RT-2 — shell menu sync at the TAIL, after every pass that can
    # add or remove routes (create/edit scaffolds, junk removal, dedup).
    # Filters join-entity routes, unions template pages (/tasks), and
    # rebuilds literal-button rails that have no props.groups anchor —
    # so the sidebar always reflects the app's final route set.
    try:
        from services.shell_menu_sync import sync_shell_menu
        _sm = sync_shell_menu(str(root))
        if _sm.get("synced"):
            applied += 1
            logger.info("shell-menu-sync: %s", _sm.get("message"))
    except Exception as e:  # noqa: BLE001
        logger.warning("sync_shell_menu failed: %s", e)

    # Plan writeback (item 7) — reconcile plan.json with shipped
    # reality (kind drift, dedup aliases, density) so the plan stays
    # the source of truth for Smith / regen / the gate's kind check.
    # Never removes pages: unmet promises stay for the gate to enforce.
    # Runs LAST before the gate so the gate judges the reconciled plan.
    try:
        from services.plan_writeback import write_back_plan
        _wb = write_back_plan(str(root))
        if _wb["changes"]:
            applied += len(_wb["changes"])
            logger.info("plan-writeback: reconciled %d field(s)",
                        len(_wb["changes"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("plan writeback failed: %s", e)

    # Regression-suite emitter — writes a registry-derived vitest suite INTO
    # the app (src/__tests__/generated/) so it carries its own regression net
    # after handoff. FORGE_EMIT_APP_TESTS=0 disables; defaults ON.
    if os.environ.get("FORGE_EMIT_APP_TESTS", "1") != "0":
        try:
            from services.test_suite_emitter import emit_test_suite
            _ts = emit_test_suite(str(root))
            if _ts.get("written"):
                applied += 1
                logger.info(
                    "test-suite-emitter: %d file(s) written (%d CRUD tests)",
                    len(_ts["written"]), _ts.get("counts", {}).get("crud_tests", 0))
            elif _ts.get("reason"):
                logger.info("test-suite-emitter skipped: %s", _ts["reason"])
        except Exception as e:  # noqa: BLE001
            logger.warning("test suite emitter failed: %s", e)

    # Trigger-contract backfill (REM-4) — pre-eventing-layer workflow JSONs
    # (and files kept by the skip-if-executable guard) get their plan-declared
    # event/schedule trigger patched in, so existing apps gain automation on
    # the next post-gen pass instead of waiting for a full regen. Additive +
    # idempotent (files already carrying a trigger are untouched).
    try:
        from services.workflow_trigger_backfill import backfill_workflow_triggers
        _tb = backfill_workflow_triggers(str(root))
        if _tb:
            applied += _tb
            logger.info("trigger-backfill: patched %d workflow file(s)", _tb)
    except Exception as e:  # noqa: BLE001
        logger.warning("trigger backfill failed: %s", e)

    # Delivery gate (F1 + G2) — the LAST word: did the artifacts deliver
    # ── Motion contract (VALIDATION) ────────────────────────────────────
    # Every app already ships a dozen cubic-beziers that nothing owns, and
    # `transition: all` — which animates whatever changes, including layout
    # properties, forcing a reflow per frame. Report-only: motion findings
    # land in the report and never fail a build, because rewriting someone's
    # stylesheet from a guard is worse than naming the problem.
    try:
        import json as _json          # module convention: json is imported locally
        from services.motion_authority import check_css
        _css = root / "src" / "app" / "globals.css"
        if _css.exists():
            _motion = check_css(_css.read_text(encoding="utf-8", errors="ignore"))
            _by_rule: dict[str, int] = {}
            for _f in _motion:
                _by_rule[_f["rule"]] = _by_rule.get(_f["rule"], 0) + 1
            logger.info("motion_authority: %d finding(s) — %s", len(_motion),
                        ", ".join(f"{k}x{v}" for k, v in sorted(_by_rule.items()))
                        or "clean")
            # Written even when clean: a missing report must mean "the gate did
            # not run", never "the gate found nothing". Those were
            # indistinguishable before, which is how a `name 'json' is not
            # defined` crash read as a passing sheet.
            (root / "contracts").mkdir(parents=True, exist_ok=True)
            (root / "contracts" / "motion-report.json").write_text(
                _json.dumps({"findings": _motion, "counts": _by_rule},
                            indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — a report must never block gen
        logger.warning("motion_authority failed: %s", exc)

    # what plan.json / nav-flow / the design brief promised? Runs after
    # every repair so it judges the final state. Writes
    # contracts/delivery-report.json. FORGE_DELIVERY_GATE=strict makes
    # error-severity misses (planned page 404s, orphan UI workflows,
    # declared-but-missing trigger buttons) fail the build; the default
    # `warn` mode reports without blocking. DeliveryGateError must
    # propagate in strict mode — that's the gate's whole point.
    try:
        from services.delivery_gate import DeliveryGateError, run_delivery_gate
    except Exception as e:  # noqa: BLE001 — import failure must not block gen
        logger.warning("delivery gate unavailable: %s", e)
    else:
        try:
            _dg = run_delivery_gate(str(root))
            _dgs = _dg.get("summary") or {}
            if _dgs.get("error", 0) or _dgs.get("warn", 0):
                logger.warning(
                    "delivery-gate: %d error(s), %d warning(s) (see delivery-report.json)",
                    _dgs.get("error", 0), _dgs.get("warn", 0),
                )
        except DeliveryGateError:
            raise  # strict mode — failing the build IS the feature
        except Exception as e:  # noqa: BLE001
            logger.warning("delivery gate failed to run: %s", e)

    # Merged scorecard — MUST be the last writer so it reads every
    # report above. Pure reader; contracts/scorecard.json is the
    # comparison substrate for the fixture fleet.
    try:
        from services.scorecard import write_scorecard
        _card = write_scorecard(root)
        if _card:
            logger.info(
                "scorecard: functional=%s design=%s composite=%s",
                _card.get("functional_score"), _card.get("design_score"),
                _card.get("composite"))
    except Exception as e:  # noqa: BLE001 — scoring must never block gen
        logger.warning("scorecard failed: %s", e)

    # Phase 7 — mark the run complete AFTER every guard has been given a
    # chance to run. A second call for the same output_dir in this
    # process will now log a warning and no-op (unless force=True).
    mark_run_complete(output_dir)
    return applied

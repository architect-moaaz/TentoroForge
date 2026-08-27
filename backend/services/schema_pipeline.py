"""Schema Pipeline — generates frontend as JSON Page schemas instead of TSX.

Iterates plan.pages (one JSON per page). Falls back to the legacy
entity-driven trio when plan.pages is absent or empty.

Feature-flagged via SCHEMA_MODE_ENABLED env var (defaults to true).
"""
from __future__ import annotations
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

from sse_helpers import sse_event

SCHEMA_MODE_ENABLED = os.getenv("SCHEMA_MODE_ENABLED", "true").lower() in ("true", "1", "yes")


async def run_schema_frontend_pipeline(
    output_dir: str,
    plan: dict[str, Any],
    description: str,
    domain_context: dict[str, Any] | None = None,
    skip_routes: set[str] | None = None,   # NEW
) -> AsyncIterator[dict]:
    """Run schema-mode frontend generation.

    Primary path: iterate plan.pages, one LLM call per page.
    Fallback: if plan.pages is empty, iterate entities (legacy trio).

    skip_routes: when supplied, plan.pages with `route` in this set are NOT
    emitted by the LLM — used by the Figma path to avoid overwriting schemas
    the deterministic mapper already produced.
    """
    start = time.time()
    yield sse_event("status", {"message": "Generating frontend via schema agent..."})
    yield sse_event("log", {"text": "[Schema] Using schema-mode (Phase 4) — emits JSON Page schemas"})

    pages = plan.get("pages") or []
    if skip_routes:
        before = len(pages)
        pages = [p for p in pages if isinstance(p, dict) and p.get("route") not in skip_routes]
        skipped = before - len(pages)
        if skipped:
            yield sse_event("log", {
                "text": f"[Schema] Skipping {skipped} page(s) already emitted by Figma mapper: "
                        f"{sorted(skip_routes)[:10]}{'...' if len(skip_routes) > 10 else ''}"
            })

    if pages:
        async for evt in _emit_per_page(output_dir, plan, pages, domain_context):
            yield evt
    elif not skip_routes:
        # Legacy path — only when plan.pages was originally empty (no skip_routes active)
        async for evt in _emit_legacy_entity_trio(output_dir, plan, domain_context):
            yield evt
    # else: skip_routes filtered everything out — pipeline is done (don't fall to legacy)

    # Completeness check FIRST — write stubs for any planned pages that didn't
    # get a schema (silent LLM failures, route classifier rejected, etc.).
    # Then regenerate the registry so it lists every plan page's file.
    stub_count = _fill_missing_with_stubs(output_dir, plan)
    if stub_count > 0:
        yield sse_event("log", {
            "text": f"[Schema] ⚠ {stub_count} page(s) had no LLM output — wrote stubs so the editor can open them"
        })

    # Upstream CRUD-route guarantee (Category-B prevention). Two structural gaps the
    # coverage/nav/button guards below each miss on their own:
    #   (1) a "New X" button that navigates to the *list* route (/bookings) instead of
    #       /bookings/new — it HAS an action, so button_audit skips it, and coverage
    #       never sees a /bookings/new reference to materialize;
    #   (2) a friendly route (/bookings) whose segment doesn't match the entity slug
    #       (ClassBooking → classbookings), so segment→entity resolution can't bridge it.
    # These passes resolve the entity from the list page's OWN dataSource, materialize
    # the missing /x/new + /x/[id]/edit forms, and repoint New/Edit buttons — so the fix
    # lands at generation time and flows through the guards below. Idempotent (also
    # re-run as a post-generate backstop in post_generate_fixes).
    try:
        from services.ensure_edit_routes import ensure_create_routes, ensure_edit_routes
        _cr = ensure_create_routes(output_dir)
        if _cr.get("created") or _cr.get("buttons"):
            yield sse_event("log", {"text": f"[Schema] create-route guarantee: +{_cr['created']} form(s), repointed {_cr['buttons']} New button(s)"})
        _er = ensure_edit_routes(output_dir)
        if _er.get("created") or _er.get("buttons"):
            yield sse_event("log", {"text": f"[Schema] edit-route guarantee: +{_er['created']} form(s), wired {_er['buttons']} Edit button(s)"})
    except Exception as _crx:
        logger.warning("[Schema] CRUD-route guarantee skipped: %s", _crx)

    # Create-page coverage: every "New X" button links to /{entity}/new, but the
    # planner often declares only some create pages — the rest 404. Generate a Form
    # page (from entity fields + the Create<Entity> workflow) for any missing one.
    try:
        import json
        from services.create_page_coverage import ensure_create_pages_llm
        from pathlib import Path as _Path
        _reg_path = _Path(output_dir) / "registry.json"
        _reg = json.loads(_reg_path.read_text()) if _reg_path.exists() else {}
        _made = await ensure_create_pages_llm(output_dir, _reg, plan, domain_context)
        if _made:
            yield sse_event("log", {"text": f"[Schema] create-page coverage: generated {', '.join(_made)}"})
    except Exception as _cov_ex:
        logger.warning("[Schema] create-page coverage skipped: %s", _cov_ex)

    # Now that every route exists, repoint/neutralize dead `navigate` targets so
    # no button 404s (naming drift, missing edit pages, orphan list links).
    try:
        from services.nav_guard import guard_nav_targets
        _nav = guard_nav_targets(output_dir)
        if _nav["repointed"] or _nav["neutralized"]:
            yield sse_event("log", {"text": f"[Schema] nav 404-guard: repointed {_nav['repointed']}, neutralized {_nav['neutralized']} dead link(s)"})
    except Exception as _nav_ex:
        logger.warning("[Schema] nav guard skipped: %s", _nav_ex)

    # Auto-wire / flag dead buttons (a Button with no action does nothing on click —
    # QA can't see this). Wires the confident cases (New→/new, label→list route),
    # reports the rest for the validate→repair loop.
    try:
        import json as _json
        from services.button_audit import audit_button_actions
        from services.crud_actions import build_workflow_index
        from services.route_slug import route_from_slug
        _sroot = Path(output_dir) / "src" / "schemas"
        _routes = [route_from_slug(str(p.relative_to(_sroot).with_suffix("")).replace("\\", "/"))
                   for p in _sroot.rglob("*.json")]
        _widx = build_workflow_index(output_dir)
        _dead = _wired = 0
        for p in _sroot.rglob("*.json"):
            try:
                _sc = _json.loads(p.read_text())
            except Exception:
                continue
            _rt = route_from_slug(str(p.relative_to(_sroot).with_suffix("")).replace("\\", "/"))
            _before = _json.dumps(_sc)
            _sc, _find = audit_button_actions(_sc, _routes, _widx, route=_rt)
            if _json.dumps(_sc) != _before:
                p.write_text(_json.dumps(_sc, indent=2))
                _wired += 1
            _dead += len(_find)
        if _wired or _dead:
            yield sse_event("log", {"text": f"[Schema] button audit: auto-wired {_wired} page(s), {_dead} dead button(s) flagged for validate/repair"})
    except Exception as _ba_ex:
        logger.warning("[Schema] button audit skipped: %s", _ba_ex)

    # Deterministic ResourceTimeline adoption: if the schema has a schedulable
    # shape (item with a date-range + resource FK), guarantee a ResourceTimeline
    # on the scheduler pages — the LLM knows the component but defaults to a Table.
    try:
        import copy as _copy
        import json as _json2
        from services.scheduler_pass import (
            detect_scheduler, build_resource_timeline, ensure_scheduler_view, is_scheduler_route)
        from services.registry import load_registry
        from services.route_slug import route_from_slug as _rfs
        _entities = (load_registry(output_dir) or {}).get("entities") or {}
        _sched = detect_scheduler(_entities)
        if _sched:
            _node = build_resource_timeline(_sched)
            _sroot2 = Path(output_dir) / "src" / "schemas"
            _added = 0
            for p in _sroot2.rglob("*.json"):
                _rt = _rfs(str(p.relative_to(_sroot2).with_suffix("")).replace("\\", "/"))
                if not is_scheduler_route(_rt, _sched):
                    continue
                try:
                    _sc = _json2.loads(p.read_text())
                except Exception:
                    continue
                _sc, _inj = ensure_scheduler_view(_sc, _copy.deepcopy(_node))
                if _inj:
                    p.write_text(_json2.dumps(_sc, indent=2))
                    _added += 1
            if _added:
                yield sse_event("log", {"text": f"[Schema] ResourceTimeline: injected on {_added} scheduler page(s) ({_sched['itemEntity']}×{_sched['resourceEntity']})"})
    except Exception as _sp_ex:
        logger.warning("[Schema] scheduler pass skipped: %s", _sp_ex)

    # Regenerate the route registry now that all (real + stub + create) schemas exist
    _regenerate_route_registry(output_dir)

    duration_ms = int((time.time() - start) * 1000)
    yield sse_event("log", {"text": f"[Schema] Completed in {duration_ms}ms"})


def _fill_missing_with_stubs(output_dir: str, plan: dict) -> int:
    """For every plan.page whose schema file doesn't exist on disk, write
    a deterministic template schema (NOT an empty stub) so the editor
    opens to a usable page. Returns the count of files written.
    """
    import json
    from pathlib import Path
    from services.route_slug import slugify_route
    from services.page_template_generator import generate_template_schema

    proj = Path(output_dir)
    pages = plan.get("pages") or []
    written = 0
    for p in pages:
        if not isinstance(p, dict):
            continue
        route = p.get("route") or ""
        if not route:
            continue
        try:
            slug = slugify_route(route)
        except ValueError:
            # Unsafe route segment — already logged by the per-page emit
            continue
        f = proj / "src" / "schemas" / f"{slug}.json"
        if f.exists():
            continue
        schema = generate_template_schema(p, plan)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(schema, indent=2))
        written += 1
    return written


def _emit_deterministic_page(output_dir: str, plan: dict, page: dict) -> bool:
    """When FORGE_DETERMINISTIC_CRUD is on, emit a routine CRUD page (list/form/detail/edit)
    straight from the entity's columns instead of calling the LLM. Writes the same
    schemas/<slug>.json the agent would. Returns True if it handled the page, else False
    (caller falls back to the LLM). Never raises into the caller's happy path."""
    import json as _json
    from pathlib import Path as _Path
    from services.deterministic_pages import (
        build_crud_page, build_dashboard_page, effective_archetype, resolve_entity,
    )
    from services.route_slug import slugify_route

    route = page.get("route") or "/"

    # FIX-2 recipe preflight — if this route already has a recipe-composed schema
    # on disk (identified by meta.recipe), the recipe path is authoritative and we
    # must not rebuild it. Prevents the widget/CRUD dispatch below from silently
    # overwriting a recipe page whose tree the user expects to see. Fully idempotent:
    # re-running the pipeline never regenerates a recipe-owned page.
    try:
        _slug = slugify_route(route)
        _existing = _Path(output_dir) / "src" / "schemas" / f"{_slug}.json"
        if _existing.exists():
            _cur = _json.loads(_existing.read_text())
            if isinstance(_cur, dict) and \
               isinstance(_cur.get("meta"), dict) and \
               _cur["meta"].get("recipe"):
                logger.info("[Schema] recipe-owned page preserved: %s", route)
                return True
    except Exception:  # noqa: BLE001 — preflight must never break the pipeline
        pass

    # Entities from the plan, else the generated registry. The page dict usually has no
    # `entity` field — infer it from the route, matched against the real entity names.
    entities = plan.get("entities") or {}
    # Full registry (entities + relations) — feeds the FK-role authority so build_crud_page
    # keeps domain FKs as editable Selects while hiding actor/tenancy FKs.
    full_registry: dict = {}
    try:
        full_registry = _json.loads((_Path(output_dir) / "registry.json").read_text())
    except Exception:
        full_registry = {}
    if not entities:
        entities = (full_registry.get("entities") or {}) if isinstance(full_registry, dict) else {}
    if not isinstance(full_registry, dict) or not full_registry.get("entities"):
        full_registry = {"entities": entities}

    # Composition Recipe Library (behind FORGE_COMPOSITION_RECIPES). When the
    # brief has `page_recipes[<route>]`, compose the page from anchor components
    # in recipe order. Returns None (silent) when the flag is off, no recipe is
    # registered for this route, or no anchor resolves to a v1 component — in
    # which case we fall through to the classic widget/CRUD/LLM dispatch.
    try:
        from services.composition.pipeline_hook import try_build_recipe_page
        _recipe_page = try_build_recipe_page(route, output_dir)
    except Exception as exc:  # noqa: BLE001 — never break the pipeline on hook
        logger.warning("[composition-hook] failed: %s", exc)
        _recipe_page = None
    if _recipe_page:
        slug = slugify_route(route)
        out_path = _Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _recipe_page["id"] = slug
        out_path.write_text(_json.dumps(_recipe_page, indent=2))
        return True

    # Dashboard/report page with planner-authored widgets → deterministic dashboard builder
    # (0 LLM): each widget renders to an aggregate/series/list dataSource + a bound node
    # straight from the registry. Returns None when no widget resolves to a real
    # entity/column → we fall through to the LLM (bespoke dashboards preserved).
    if isinstance(page.get("widgets"), list) and page.get("widgets"):
        try:
            from services.schema_prompt import _load_design_spec
            _dspec = _load_design_spec(output_dir)
        except Exception:
            _dspec = {}
        dash = build_dashboard_page(page, entities, _dspec)
        if dash:
            slug = slugify_route(route)
            out_path = _Path(output_dir) / "src" / "schemas" / f"{slug}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            dash["id"] = slug
            out_path.write_text(_json.dumps(dash, indent=2))
            return True
        # else: no valid widgets — fall through to the CRUD/LLM dispatch below.

    # Route shape is authoritative for the CRUD archetype; planner hints are fallback.
    arch = effective_archetype(route, page.get("archetype"), page.get("type"))
    if not arch:
        return False
    entity = resolve_entity(route, page.get("entity"), entities.keys())
    if not entity:
        return False
    cols = (entities.get(entity) or {}).get("fields")
    if not cols:
        return False
    try:
        from services.schema_prompt import _load_design_spec
        design_spec = _load_design_spec(output_dir)
    except Exception:
        design_spec = {}
    # The planner may author a per-field form spec (page['fields']); pass it through so
    # build_form_page merges it over the registry-derived defaults (registry backstops
    # omissions, validates control↔SQL-type compatibility).
    field_specs = page.get("fields") if isinstance(page.get("fields"), list) else None
    page_dict = build_crud_page(arch, entity, cols, route, design_spec, entities=entities,
                                field_specs=field_specs, registry=full_registry,
                                output_dir=output_dir, page_hint=page)
    if not page_dict:
        return False
    slug = slugify_route(route)
    out_path = _Path(output_dir) / "src" / "schemas" / f"{slug}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_dict["id"] = slug
    out_path.write_text(_json.dumps(page_dict, indent=2))
    return True


async def _emit_per_page(
    output_dir: str, plan: dict, pages: list[dict], domain_context: dict | None
) -> AsyncIterator[dict]:
    import traceback as tb
    import os as _os
    from agents.page_schema_agent import run_page_schema_agent
    from services.crud_actions import merge_crud_into_page

    def _merge_actions_before_agent(page: dict) -> dict:
        """Merge derived CRUD actions into the page BEFORE the agent runs so the
        prompt the model sees already has its full actions[]. Annotates the page
        with the same fields _apply_plan_binding threads to apply_bindings.
        Best-effort: on any failure, return the page unchanged."""
        try:
            _wf_dir = _os.path.join(output_dir, "workflows")
            _existing_wf = {
                f[:-5]
                for f in (_os.listdir(_wf_dir) if _os.path.isdir(_wf_dir) else [])
                if f.endswith(".json")
            }
            merged = merge_crud_into_page(page, plan, _existing_wf)
            merged["_existing_workflows"] = sorted(_existing_wf)
            from services.crud_actions import build_workflow_index
            merged["_workflow_index"] = build_workflow_index(output_dir)
            merged["_page_type"] = page.get("type")
            merged["_route"] = page.get("route")
            return merged
        except Exception:
            logger.warning("[Schema] action pre-merge skipped for %s", page.get("route"))
            return page

    total = len(pages)
    yield sse_event("log", {"text": f"[Schema] Generating {total} page{'s' if total != 1 else ''}..."})
    # Conversational narration in the chat (persistent bubble; no [Tag] prefix).
    from services import chat_flavor
    _pages_start = chat_flavor.start("pages")
    if _pages_start:
        yield sse_event("message", {"text": _pages_start})

    failed: list[dict] = []  # {page, route, error_type, message, traceback}
    succeeded = 0
    _BINDING_REPORTS: list = []
    _WIRING_REPORTS: list = []

    # ── Concurrency: generate pages in PARALLEL (bounded) instead of one-by-one.
    # Page generation is the slowest phase — one throttle-prone LLM call per page,
    # previously run sequentially so every 429/529 backoff stacked end-to-end. Each
    # page only writes its own schemas/<slug>.json and appends to the shared report
    # lists (GIL-safe appends, no cross-page file contention), so running them
    # concurrently is safe. The semaphore caps in-flight calls so we don't fire all
    # pages at once and amplify throttling. Tune with FORGE_PAGE_CONCURRENCY.
    import asyncio
    _CAP = max(1, int(_os.environ.get("FORGE_PAGE_CONCURRENCY", "5")))
    _sem = asyncio.Semaphore(_CAP)

    async def _run_one(page: dict):
        """Merge actions → run the page agent → apply plan binding, under the cap.
        Returns (route, ok, failure_entry_or_None). Never raises."""
        page = _merge_actions_before_agent(page)
        route = page.get("route", "?")
        # Deterministic CRUD (default ON): build routine list/form/detail/edit pages from the
        # schema instead of the LLM — 0 LLM calls (no chunking) for the routine ~80% of pages,
        # and more reliable (no malformed/phantom output). Route shape gates it; bespoke pages
        # (dashboards, analytics, custom) return None → LLM. Falls back to the LLM on any miss
        # or error. Opt out with FORGE_DETERMINISTIC_CRUD=0.
        if _os.environ.get("FORGE_DETERMINISTIC_CRUD", "on").strip().lower() not in ("0", "false", "off", "no"):
            try:
                if _emit_deterministic_page(output_dir, plan, page):
                    logger.info("[Schema] ⚡ deterministic CRUD page (no LLM): %s", route)
                    return (route, True, None)
            except Exception:
                logger.warning("[Schema] deterministic CRUD failed for %s — LLM fallback", route)
        async with _sem:
            try:
                await run_page_schema_agent(output_dir, plan, page, domain_context=domain_context)
                await _apply_plan_binding(output_dir, plan, page, _BINDING_REPORTS, _WIRING_REPORTS)
                return (route, True, None)
            except Exception as e:
                logger.exception("[Schema] page %s failed", route)
                return (route, False, {
                    "page": page,
                    "route": route,
                    "error_type": type(e).__name__,
                    "message": str(e)[:200],
                    "traceback": "\n".join(tb.format_exc().splitlines()[-3:]),
                })

    # ── Pass 1: every page, concurrently (capped) ────────────────────────────
    valid = [p for p in pages if isinstance(p, dict)]
    if len(valid) != len(pages):
        yield sse_event("log", {"text": "[Schema] ⚠ Skipped malformed page entr(ies)"})
    # Composition Recipe Library (behind FORGE_COMPOSITION_RECIPES). Partition
    # the worklist for observability — recipe-owned pages will fast-exit through
    # the deterministic path (_emit_deterministic_page → try_build_recipe_page),
    # never touching the LLM. Doesn't change dispatch — the deterministic path
    # still runs first per-page — but gives an accurate status count and log.
    _recipe_count = 0
    try:
        from services.composition.pipeline_hook import filter_pages_owned_by_recipes
        _llm_pages, _recipe_routes = filter_pages_owned_by_recipes(valid, output_dir)
        _recipe_count = len(_recipe_routes)
        if _recipe_count:
            yield sse_event("log", {
                "text": f"[Schema] ⚡ {_recipe_count} page(s) from composition recipes: {_recipe_routes}",
            })
    except Exception as _crl_exc:  # noqa: BLE001 — filter must never break pipeline
        logger.warning("[Schema] recipe partition failed (non-fatal): %s", _crl_exc)
    _llm_count = len(valid) - _recipe_count
    _status_msg = f"Generating {len(valid)} pages ({_CAP} in parallel)"
    if _recipe_count:
        _status_msg += f" — {_recipe_count} from recipes, {_llm_count} via LLM"
    _status_msg += "..."
    yield sse_event("status", {"message": _status_msg})
    _tasks = [asyncio.create_task(_run_one(p)) for p in valid]
    for _fut in asyncio.as_completed(_tasks):
        route, ok, err = await _fut
        if ok:
            succeeded += 1
            yield sse_event("log", {"text": f"[Schema] ✓ {route}"})
        else:
            failed.append(err)
            yield sse_event("log", {
                "text": f"[Schema] ⚠ {route} failed ({err['error_type']}): {err['message'][:100]}"
            })

    # ── Pass 2: retry failed pages, concurrently (capped) ────────────────────
    if failed:
        yield sse_event("log", {
            "text": (
                f"[Schema] Pass 1 done: {succeeded}/{total} succeeded. "
                f"Retrying {len(failed)} failed page(s)..."
            )
        })
        _retry_pages = [e["page"] for e in failed]
        failed = []
        _rtasks = [asyncio.create_task(_run_one(p)) for p in _retry_pages]
        for _fut in asyncio.as_completed(_rtasks):
            route, ok, err = await _fut
            if ok:
                succeeded += 1
                yield sse_event("log", {"text": f"[Schema] ✓ (retry) {route}"})
            else:
                failed.append(err)
                yield sse_event("log", {
                    "text": f"[Schema] ⚠ (retry) {route} failed again: {err['message'][:100]}"
                })

    # ── Summary ───────────────────────────────────────────────────────────────
    yield sse_event("log", {
        "text": f"[Schema] Generation summary: {succeeded}/{total} succeeded, {len(failed)} failed"
    })
    # Celebratory completion bubble in the chat.
    _pages_done = chat_flavor.done("pages", succeeded)
    if _pages_done and succeeded:
        yield sse_event("message", {"text": _pages_done})
    if failed:
        # Group by error type for visibility
        by_type: dict[str, list[str]] = {}
        for entry in failed:
            by_type.setdefault(entry["error_type"], []).append(entry["route"])
        for err_type, routes in by_type.items():
            yield sse_event("log", {
                "text": (
                    f"[Schema]   {err_type} ({len(routes)}): "
                    f"{', '.join(routes[:5])}{'...' if len(routes) > 5 else ''}"
                )
            })
        # Short traceback for the first few failures (debugging aid)
        for entry in failed[:3]:
            yield sse_event("log", {
                "text": f"[Schema] {entry['route']} traceback: {entry['traceback'][:300]}"
            })

    # ── Aggregate plan-driven binding report ────────────────────────────────────
    try:
        import json as _json
        from pathlib import Path
        (Path(output_dir) / "binding-report.json").write_text(
            _json.dumps(_BINDING_REPORTS, indent=2))
    except Exception:
        pass

    # ── Aggregate LLM completeness-guard report ─────────────────────────────────
    try:
        import json as _json
        (Path(output_dir) / "wiring-report.json").write_text(
            _json.dumps(_WIRING_REPORTS, indent=2))
    except Exception:
        pass


async def _apply_plan_binding(output_dir: str, plan: dict, page: dict, reports: list,
                              wiring_reports: list | None = None) -> None:
    """Plan-driven binding (LLM path): wire row/page action buttons to workflows
    declared in the plan. The page agent already emits data binding
    (dataSources/Repeat); the per-concern idempotency in apply_bindings leaves
    that intact and only adds missing button workflow/args. Best-effort — any
    failure is logged and skipped so it never breaks generation."""
    try:
        import json
        from pathlib import Path
        from services.route_slug import slugify_route
        from services.schema_binding import apply_bindings
        from services.llm_plan_binding_adapter import build_page_intent

        route = page.get("route") or ""
        if not route:
            return
        try:
            slug = slugify_route(route)
        except ValueError:
            return
        schema_file = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        if not schema_file.exists():
            return
        schema = json.loads(schema_file.read_text())

        # Merge deterministic CRUD actions (nav New/Edit + Delete workflow) into
        # the page before building the intent, so the binding pass wires them.
        from services.crud_actions import (
            merge_crud_into_page, build_workflow_index, resolvable_workflow_names,
        )
        # Every string the RUNTIME resolves to a workflow, not filename stems.
        # Second site of register BA-1 — the runtime caches by `definition.id`
        # AND `definition.name`, so a renamed file made its workflow invisible
        # here and the derived button was silently withheld.
        _existing_wf = resolvable_workflow_names(output_dir)
        page = merge_crud_into_page(page, plan, _existing_wf)
        # Thread workflow set + index + page-type/route so apply_bindings can run
        # apply_form_bindings (Form submit → Create/Update<Entity>) and
        # canonicalize_and_guard_workflow_buttons (fix casing / strip phantoms).
        page["_existing_workflows"] = sorted(_existing_wf)
        page["_workflow_index"] = build_workflow_index(output_dir)
        # Status-transition workflow index — lets the binding pass MAP an invented
        # status action (Confirm/Cancel) to the real <Entity>Status workflow with
        # the right {idVar, statusVar} args, instead of stripping it as a phantom.
        from services.workflow_action_mapper import index_status_workflows
        page["_status_index"] = index_status_workflows(output_dir)
        page["_page_type"] = page.get("type")
        page["_route"] = page.get("route")

        intent = build_page_intent(page, plan)
        bound, report = apply_bindings(schema, intent, plan)
        # Align form field names to the entity's real DB columns so a create/edit
        # submit actually maps to the database (the agent emits snake_case / invented
        # field names that otherwise silently fail to save).
        try:
            from services.form_field_align import align_form_fields
            _reg_p = Path(output_dir) / "registry.json"
            _reg = json.loads(_reg_p.read_text()) if _reg_p.exists() else {}
            bound, _afr = align_form_fields(bound, page.get("entity"), _reg)
            if _afr.get("renamed"):
                logger.info("[FormAlign] %s: renamed %d field(s) to real columns", page.get("route"), _afr["renamed"])
        except Exception as _fa_ex:
            logger.warning("[FormAlign] %s skipped: %s", page.get("route"), _fa_ex)

        # Normalize JS-style expressions (===, condition prop) to feel-lite so the
        # renderer doesn't ParseError ("Unexpected token: Eq") on the page.
        try:
            from services.expr_normalizer import normalize_expressions
            bound, _enr = normalize_expressions(bound)
            if _enr.get("fixed"):
                logger.info("[ExprNorm] %s: normalized %d expression(s)", page.get("route"), _enr["fixed"])
        except Exception as _en_ex:
            logger.warning("[ExprNorm] %s skipped: %s", page.get("route"), _en_ex)

        schema_file.write_text(json.dumps(bound, indent=2))
        reports.append(report)

        # ── LLM completeness guard ──────────────────────────────────────────
        # Best-effort safety net over the deterministic binding: ensure every
        # actionable button is tied to a real workflow / route. Only applies
        # repairs the guard can validate; failures only log (never abort).
        try:
            from agents.wiring_guard import run_wiring_guard, make_anthropic_guard_llm

            real_workflows = set(_existing_wf)
            real_routes = {
                p.get("route") for p in (plan.get("pages") or [])
                if isinstance(p, dict) and p.get("route")
            }
            call_llm = make_anthropic_guard_llm() if _os.environ.get("ANTHROPIC_API_KEY") else None
            guarded, wiring_report = await run_wiring_guard(
                bound, real_workflows=real_workflows, real_routes=real_routes,
                call_llm=call_llm)
            schema_file.write_text(json.dumps(guarded, indent=2))
            if wiring_reports is not None:
                wiring_report["route"] = route
                wiring_reports.append(wiring_report)
        except Exception as guard_ex:
            logger.warning("[Guard][LLM] %s skipped: %s", page.get("route"), guard_ex)

        # ── Aggregate-spec floor ────────────────────────────────────────────
        # Ensure MetricTile bindings to op:"aggregate" sources resolve to real
        # numbers (never a literal {{…}}). This is the TEXT-path equivalent of
        # the figma pipeline's per-page floor; the page agent emits the bindings
        # but may omit/mis-spec the metrics, so reconcile against the registry.
        try:
            from services.aggregate_spec import reconcile_page_file

            _reg_path = Path(output_dir) / "registry.json"
            _registry = json.loads(_reg_path.read_text()) if _reg_path.exists() else {}
            _agg = reconcile_page_file(schema_file, _registry)
            if _agg.get("synthesised") or _agg.get("demoted"):
                logger.info("[Aggregate][LLM] %s: %s synthesised, %s demoted",
                            page.get("route"), _agg["synthesised"], _agg["demoted"])
        except Exception as agg_ex:
            logger.warning("[Aggregate][LLM] %s skipped: %s", page.get("route"), agg_ex)
    except Exception as bind_ex:
        logger.warning("[Binding][LLM] %s skipped: %s", page.get("route"), bind_ex)


async def _emit_legacy_entity_trio(
    output_dir: str, plan: dict, domain_context: dict | None
) -> AsyncIterator[dict]:
    """Legacy path — used only when plan.pages is empty. Same code as before."""
    from agents.feature_slice_schema_agent import run_feature_slice_schema_agent
    raw_entities = plan.get("data_models") or plan.get("entities") or []
    if isinstance(raw_entities, dict):
        entities: list[dict] = [
            {"name": name, **(defn if isinstance(defn, dict) else {})}
            for name, defn in raw_entities.items()
        ]
    else:
        entities = raw_entities
    yield sse_event("log", {"text": f"[Schema] (legacy trio) {len(entities)} entit{'y' if len(entities)==1 else 'ies'} to process"})
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = entity.get("name", "Unknown")
        if entity.get("legacy_tsx_mode") is True:
            continue
        entity_plan = {**plan, "entity": entity}
        yield sse_event("status", {"message": f"Generating schemas for {name}..."})
        try:
            await run_feature_slice_schema_agent(output_dir, entity_plan, domain_context=domain_context)
            yield sse_event("log", {"text": f"[Schema] ✓ {name} schemas emitted"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Schema] ⚠ {name} failed: {e}"})


_SCHEMA_LOAD_TS = '''import { Page } from "@tentoroforge/schema";
import type { z } from "zod";

// Module-level cache: schema name → validated Page object (per-process in RSC).
const cache = new Map<string, z.infer<typeof Page>>();

/** Validate a raw JSON object against the Page schema and cache the result.
 * Validation is ADVISORY: generated schemas use binding expressions
 * ("{{stats.total}}") in typed fields and may omit fields that are optional at
 * runtime (e.g. layout). The Engine resolves/tolerates these, so a strict-schema
 * miss must NOT 500 the page — warn and render the raw schema as-is. */
export function loadSchema(name: string, raw: unknown): z.infer<typeof Page> {
  const hit = cache.get(name);
  if (hit) return hit;
  const result = Page.safeParse(raw);
  if (result.success) {
    cache.set(name, result.data);
    return result.data;
  }
  const msg = result.error.errors
    .map((e) => `${e.path.join(".") || "<root>"}: ${e.message}`)
    .join("; ");
  console.warn(`[schema] '${name}' did not strictly validate (${msg}); rendering as-is.`);
  const data = raw as z.infer<typeof Page>;
  cache.set(name, data);
  return data;
}
'''


def _regenerate_route_registry(output_dir: str) -> None:
    """Scan src/schemas/**/*.json and write registry.ts keyed by route."""
    from pathlib import Path
    from services.route_slug import route_from_slug

    schemas_root = Path(output_dir) / "src" / "schemas"
    if not schemas_root.exists():
        return
    registry_path = schemas_root / "registry.ts"

    entries: list[str] = []
    for json_file in sorted(schemas_root.rglob("*.json")):
        rel = json_file.relative_to(schemas_root)
        slug = str(rel.with_suffix("")).replace("\\", "/")
        route = route_from_slug(slug)
        rel_import = "./" + str(rel).replace("\\", "/")
        entries.append(f'  "{route}": () => import("{rel_import}"),')

    body = "\n".join(entries) if entries else ""
    registry_path.write_text(
        '// Auto-generated by schema_pipeline — do not edit by hand.\n'
        '// Keys are routes (with leading slash). Paths mirror src/schemas/.\n\n'
        'import { loadSchema } from "./load";\n\n'
        'export const schemas: Record<string, () => Promise<unknown>> = {\n'
        f'{body}\n'
        '};\n\n'
        'export async function getSchema(route: string): Promise<ReturnType<typeof loadSchema>> {\n'
        '  const loader = schemas[route];\n'
        '  if (!loader) throw new Error(`unknown route \'${route}\'`);\n'
        '  const raw = await loader();\n'
        '  return loadSchema(route, (raw as any).default ?? raw);\n'
        '}\n'
    )

    # registry.ts imports `loadSchema` from "./load" — ensure that module exists
    # next to it. It's a foundation-template file that doesn't reliably survive
    # into the generated src/schemas/ dir, and without it the /[entity] route
    # fails to compile ("Module not found: Can't resolve './load'").
    load_path = schemas_root / "load.ts"
    if not load_path.exists():
        load_path.write_text(_SCHEMA_LOAD_TS)

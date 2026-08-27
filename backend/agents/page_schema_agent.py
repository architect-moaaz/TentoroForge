"""Page Schema Agent — generates ONE JSON Page schema for a single page entry.

Replaces feature_slice_schema_agent's hardcoded list/detail/form trio. Each
call handles one page from plan.pages and writes one file. Routes determine
the on-disk path.

Signature mirrors the rest of the agent layer:
  run_page_schema_agent(output_dir, plan, page, domain_context=None) -> None
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from services.route_slug import route_from_slug, slugify_route
from services.schema_prompt import build_schema_prompt
from services.schema_normalizer import normalize_v2_schema
from services.illustration_bundler import bundle_illustrations_for_schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Illustrations MCP server registration
# ---------------------------------------------------------------------------
# The schema agent exposes the unDraw illustrations MCP server to the LLM so
# it can call list_illustrations / get_illustration_svg while composing a
# Page schema. We register it as a *stdio subprocess* MCP server — the SDK
# forwards the config to the bundled `claude` CLI which then launches the
# illustrations server as a child process and speaks MCP over its stdio.
#
# We initially tried in-process registration via McpSdkServerConfig
# (instance=fastmcp._mcp_server) but that path is incompatible with the
# bundled subprocess CLI transport: it raised CLIConnectionError
# "ProcessTransport is not ready for writing" during the MCP handshake
# because the in-process server lives in *our* Python process, not the CLI's.
_ILLUSTRATIONS_SERVER_NAME = "illustrations"
_ILLUSTRATIONS_TOOL_NAMES = ("list_illustrations", "get_illustration_svg")
# claude_agent_sdk exposes MCP tools to the LLM as `mcp__<server>__<tool>`.
_ILLUSTRATIONS_ALLOWED_TOOLS = [
    f"mcp__{_ILLUSTRATIONS_SERVER_NAME}__{t}" for t in _ILLUSTRATIONS_TOOL_NAMES
]

# backend/agents/page_schema_agent.py -> backend/
_BACKEND_DIR = Path(__file__).resolve().parents[1]

_illustrations_mcp_config: dict | None = None


def _purge_custom_enabled() -> bool:
    """Phase 6d — return True when FORGE_PURGE_CUSTOM is on.

    Off by default. Flip on with any of ``1`` / ``true`` / ``yes`` /
    ``on`` (case-insensitive). Reading the env per-call is intentional
    for testability + runtime toggling.
    """
    raw = os.environ.get("FORGE_PURGE_CUSTOM", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_illustrations_mcp_config() -> dict:
    """Build (once) the McpStdioServerConfig for our illustrations server.

    The SDK forwards this dict to the bundled `claude` CLI which spawns
    `python -m illustrations_mcp.illustrations_server` as a child process.
    PYTHONPATH is set to backend/ so the subprocess can locate the
    `illustrations_mcp` package — the child process starts fresh and
    doesn't inherit our sys.path.
    """
    global _illustrations_mcp_config
    if _illustrations_mcp_config is None:
        # Preserve any inherited PYTHONPATH segments and prepend our backend dir.
        existing_pp = os.environ.get("PYTHONPATH", "")
        pythonpath = (
            f"{_BACKEND_DIR}{os.pathsep}{existing_pp}" if existing_pp else str(_BACKEND_DIR)
        )
        _illustrations_mcp_config = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "illustrations_mcp.illustrations_server"],
            "env": {"PYTHONPATH": pythonpath},
        }
    return _illustrations_mcp_config


def build_actions_directive(page: dict) -> str:
    """Build a prompt block instructing the model to render the EXACT action
    buttons declared on the page (Delete/Approve/New/...), placed correctly.

    Returns "" when the page has no actions. The platform wires each button's
    workflow/onClick in a later binding pass, so the model must only render the
    labeled button in the right place — it must NOT invent its own wiring.

    Placement per action kind:
      - row_action → one button inside EACH list row
      - page_action → page-level action button (header/toolbar)
      - navigate    → a navigation button
    """
    actions = (page or {}).get("actions") or []
    if not actions:
        return ""

    _PLACEMENT = {
        "row_action": "place one inside EACH list row (row action)",
        "page_action": "page-level action button (header/toolbar)",
        "navigate": "a navigation button",
    }
    lines: list[str] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        label = a.get("label")
        if not label:
            continue
        kind = a.get("kind") or "page_action"
        placement = _PLACEMENT.get(kind, _PLACEMENT["page_action"])
        lines.append(f'- "{label}" — {placement}')
    if not lines:
        return ""

    return (
        "## Action buttons (REQUIRED — render exactly these)\n"
        "Render a Button with EXACTLY this label text for each action below. "
        "Do NOT add your own workflow/onClick — the platform wires the action "
        "automatically; you only render the labeled button in the right place.\n"
        + "\n".join(lines)
        + "\n"
    )


async def run_page_schema_agent(
    output_dir: str,
    plan: dict,
    page: dict,
    domain_context: dict | None = None,
) -> None:
    """Generate a single Page JSON schema and write it to disk.

    Args:
        output_dir: Absolute path to the app output directory.
        plan: The full project plan dict (entities, design, etc).
        page: A single page entry from plan.pages — must have:
              - 'route': "/notes" / "/notes/new" / "/notes/[id]"
              - 'entity': name of the primary entity bound on this page
                         (or None for entity-free pages like dashboards)
              - 'type': "list" | "detail" | "form" | "dashboard" | "settings"
              - 'name': human-readable name
        domain_context: Optional domain-specific context injected into prompts.
    """
    os.environ.pop("CLAUDECODE", None)
    route = page.get("route") or "/"
    slug = slugify_route(route)
    out_path = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Composition Recipe Library — restrict LLM authoring on recipe-owned
    # routes. Behind FORGE_COMPOSITION_RECIPES. The recipe path in
    # schema_pipeline already wrote a fully-composed page schema; letting
    # the LLM run again would silently overwrite it. Defence-in-depth so
    # secondary callers (create_page_coverage etc.) can't clobber it either.
    try:
        from services.composition.pipeline_hook import is_route_recipe_owned
        if is_route_recipe_owned(route, output_dir):
            logger.info(
                "[Schema] %s owned by composition recipe — skipping LLM authoring",
                route,
            )
            return
    except Exception as exc:  # noqa: BLE001 — hook must never break the LLM path
        logger.warning("[Schema] recipe-ownership check failed: %s", exc)

    # Phase 3 — Dashboard Authority. When FORGE_DASHBOARD_AUTHORITY is on,
    # the LLM does NOT author dashboard pages; the deterministic
    # ``apply_dashboard_maquette`` composer is the sole writer for them.
    # Off-by-default gate so existing behaviour is preserved. Fail-open
    # on any exception so a misbehaving flag can't break the LLM path.
    try:
        from services.dashboard_authority import (
            is_dashboard_authority_enabled,
            is_dashboard_page,
        )
        if is_dashboard_authority_enabled() and is_dashboard_page(page):
            logger.info(
                "[Schema] %s is a dashboard — skipping LLM (composer is authority)",
                route,
            )
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Schema] dashboard-authority check failed: %s", exc)

    # Phase 6 — Collection + Record Authority. Same shape as dashboard,
    # extended to two more artifact kinds. Independent env gates
    # (FORGE_COLLECTION_AUTHORITY, FORGE_RECORD_AUTHORITY) so the
    # rollout can be staged per artifact as fixture regen confirms
    # each composer.
    try:
        from services.artifact_authority import (
            is_authority_enabled,
            is_page_of_kind,
        )
        for _artifact in ("collection", "record"):
            if is_authority_enabled(_artifact) and is_page_of_kind(page, _artifact):
                logger.info(
                    "[Schema] %s is a %s — skipping LLM (composer is authority)",
                    route, _artifact,
                )
                return
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Schema] artifact-authority check failed: %s", exc)

    # Phase 6d — Purge "custom" escape. Behind FORGE_PURGE_CUSTOM.
    # When on, the LLM authors ONLY the three known artifact kinds
    # (dashboard/collection/record) OR pages the plan marks
    # ``bespoke: true``. Any other page type stops here with a coherent
    # skip reason the REVISE loop can pick up — no more "custom" pages
    # sneaking through unowned by any composer or authority.
    #
    # Fail-open: any import/lookup failure preserves legacy behaviour.
    try:
        from services.dashboard_authority import (
            is_dashboard_page as _is_dashboard_page,
        )
        from services.artifact_authority import (
            is_page_of_kind as _artifact_is_page_of_kind,
        )
        if _purge_custom_enabled():
            _is_known_kind = (
                _is_dashboard_page(page)
                or _artifact_is_page_of_kind(page, "collection")
                or _artifact_is_page_of_kind(page, "record")
            )
            _is_bespoke = bool(page.get("bespoke")) is True
            if not (_is_known_kind or _is_bespoke):
                _type = str(page.get("type") or page.get("archetype") or "?")
                logger.warning(
                    "[Schema] %s has unknown page type %r — purge-custom "
                    "rejected; add bespoke: true to plan.pages entry, or use "
                    "one of dashboard/list/kanban/calendar/cards/timeline/"
                    "form/detail/edit/create/view",
                    route, _type,
                )
                # Emit a coherent stub so the REVISE loop sees SOMETHING
                # on disk + can retry with a normalised plan entry.
                out_path.write_text(json.dumps(_minimal_schema(slug, _type), indent=2))
                return
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Schema] purge-custom check failed: %s", exc)

    schema_dict = await _generate_schema_for_page(plan, page, slug, domain_context, output_dir=output_dir)
    # Self-describing id + route MUST match the file path — the file name, the
    # registry key, and the id are all derived from `slug`, but the LLM often
    # writes its own `route` into the schema body (e.g. a "dashboard"-style page
    # emits route "/dashboard", a watchlist page emits "/watchlist-items"). If we
    # trust that, nav-flow links to a route that was never registered and every
    # nav item 404s. Pin route to the canonical registry key so id, filename,
    # registry, and nav can never diverge.
    schema_dict["id"] = slug
    schema_dict["route"] = route_from_slug(slug)
    schema_dict.setdefault("schemaVersion", "2")

    # ── Contract-constrained authoring (anomaly-removal move 3) ──
    # Judge the LLM's output against the SAME contract the renderer
    # enforces BEFORE writing. On violations, one revise turn with the
    # exact violation list; the post-gen page-contract gate remains the
    # backstop for anything that survives. FORGE_PAGE_CONTRACT_RETRY=
    # off disables the retry (validation still logs).
    try:
        from services.page_contract_validator import (
            format_issues_for_revise, load_contracts, validate_schema_dict,
        )
        _contracts = load_contracts()
        if _contracts is not None:
            _issues = validate_schema_dict(schema_dict, slug, _contracts)
            if _issues:
                logger.warning(
                    "[Schema] %s violates component contract (%d issue(s)): %s",
                    slug, len(_issues),
                    "; ".join(i["code"] for i in _issues))
                if os.environ.get(
                        "FORGE_PAGE_CONTRACT_RETRY", "on").lower() != "off":
                    _fixed = await _generate_schema_for_page(
                        plan, page, slug, domain_context,
                        output_dir=output_dir,
                        revise_notes=format_issues_for_revise(_issues),
                    )
                    if isinstance(_fixed, dict):
                        _fixed["id"] = slug
                        _fixed["route"] = route_from_slug(slug)
                        _fixed.setdefault("schemaVersion", "2")
                        _still = validate_schema_dict(_fixed, slug, _contracts)
                        if len(_still) < len(_issues):
                            schema_dict = _fixed
                        logger.info(
                            "[Schema] %s contract retry: %d → %d issue(s)%s",
                            slug, len(_issues), len(_still),
                            "" if len(_still) < len(_issues)
                            else " (kept original)")
    except Exception:  # noqa: BLE001 — validation must never block authoring
        logger.exception("[Schema] contract check failed for %s (continuing)",
                         slug)

    out_path.write_text(json.dumps(schema_dict, indent=2))
    logger.info("[Schema] wrote %s", out_path)

    # ── Page critic (Sprint 3 of "Forge Great Again") ──
    # For designer-authored pages, run a text-only design critic that
    # scores hierarchy, brand echo, semantic color, empty states, and
    # signature-move usage. Persist the verdict to reports/page-critic/
    # so we learn where the Designer falls short. When FORGE_PAGE_CRITIC_
    # REVISE is on and the critic flagged HIGH-severity gaps, run one
    # more Designer turn with the gaps as REVISE notes.
    #
    # Fail-open: any error here logs + moves on. The critic never blocks
    # generation. This is observability first; the REVISE loop is
    # separately gated so latency doesn't double until quality is proven.
    try:
        if schema_dict.get("_designer_authored") is True:
            from services.page_critic import (
                page_critic_enabled, revise_loop_enabled,
                critique_page_schema, persist_critique,
                has_high_severity_gap, format_gaps_for_revise,
            )
            if page_critic_enabled():
                from services.design_context_pack import (
                    _page_purpose_block, _design_brief_block,
                    _brief_signature_move_names,
                )
                purpose_prose = _page_purpose_block(plan, page)
                brief_prose = _design_brief_block(output_dir)

                # Sprint 6/7 — load brief details the detectors need to
                # check signature-move presence + brand-color echo.
                _brief_primary_hex = None
                _brief_moves: list[str] = []
                try:
                    from services.design_brief_to_prompt import load_brief_from_disk
                    _b = load_brief_from_disk(output_dir)
                    if _b is not None:
                        _palette = getattr(_b, "palette", None)
                        if _palette is not None:
                            _brief_primary_hex = getattr(_palette, "brand", None)
                        _brief_moves = sorted(_brief_signature_move_names(output_dir))
                except Exception:  # noqa: BLE001 — detectors handle None gracefully
                    pass

                # Sprint 8 — best-effort screenshot for vision critic. Returns
                # None when the screenshot service isn't configured or the
                # capture fails; critic falls back to text-only mode.
                _shot_bytes = None
                try:
                    from services.page_critic import vision_enabled
                    if vision_enabled():
                        from services.page_screenshot import capture_page_screenshot
                        _shot_bytes = capture_page_screenshot(
                            output_dir, slug, route_from_slug(slug),
                        )
                except Exception:  # noqa: BLE001
                    pass

                critique = await critique_page_schema(
                    schema=schema_dict,
                    page_purpose_prose=purpose_prose,
                    brief_prose=brief_prose,
                    brief_primary_hex=_brief_primary_hex,
                    brief_signature_moves=_brief_moves,
                    screenshot_bytes=_shot_bytes,
                )
                persist_critique(output_dir, slug, critique)
                # Sprint 9 — append this page's fingerprint to the
                # per-project memory ledger so later pages can read it.
                # No-op when FORGE_PAGE_DESIGN_MEMORY is off.
                try:
                    from services.page_design_memory import record_page
                    record_page(
                        output_dir,
                        slug=slug,
                        page_type=(page.get("type") or page.get("page_type") or ""),
                        critique=critique,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[page-memory] record_page failed for %s (continuing)",
                        slug,
                    )
                logger.info(
                    "[page-critic] %s score=%s passes=%s gaps=%d",
                    slug, critique.get("score"), critique.get("passes"),
                    len(critique.get("gaps") or []),
                )
                # REVISE round — opt-in. One extra turn max, feeds
                # critic gaps back into the Designer as a REVISE block.
                if revise_loop_enabled() and has_high_severity_gap(critique):
                    revise_notes = format_gaps_for_revise(critique)
                    logger.info(
                        "[page-critic] %s — running REVISE round "
                        "(gaps: %d)", slug, len(critique.get("gaps") or []),
                    )
                    revised = await _generate_schema_for_page(
                        plan, page, slug, domain_context,
                        output_dir=output_dir,
                        revise_notes=revise_notes,
                    )
                    if isinstance(revised, dict):
                        revised["id"] = slug
                        revised["route"] = route_from_slug(slug)
                        revised.setdefault("schemaVersion", "2")
                        revised["_designer_authored"] = True
                        revised["_designer_revised"] = True
                        out_path.write_text(json.dumps(revised, indent=2))
                        schema_dict = revised
                        logger.info(
                            "[page-critic] %s — REVISE applied", slug,
                        )
    except Exception:  # noqa: BLE001 — critic is best-effort
        logger.exception(
            "[page-critic] failed for %s — schema already written, continuing",
            slug,
        )

    # Visual enrichment post-pass — retrofits photoUrl on Avatar nodes,
    # backgroundImage on Hero nodes, and icon on FeatureCard nodes that
    # the LLM left blank. Reads the project's design-spec for per-app
    # URLs (loginBackground / dashboardHero / facePool) and falls back to
    # a curated default pool otherwise. Only fills blank fields — any
    # value the LLM supplied is preserved.
    try:
        from agents.design_agent import load_design_spec
        from services.schema_visual_enricher import enrich_schema_visuals
        design_spec = load_design_spec(output_dir) or {}
        n = enrich_schema_visuals(schema_dict, design_spec=design_spec, route=page.get("route"))
        if n > 0:
            out_path.write_text(json.dumps(schema_dict, indent=2))
            logger.info("[Schema] enriched %d visual node(s) in %s", n, out_path.name)
    except Exception:
        logger.exception(
            "[Schema] visual enrichment failed for %s — schema already written, continuing",
            slug,
        )

    # Bundle any illustration assets referenced in the schema into the output dir.
    # Wrapped in its own try/except so a bundling failure cannot lose a schema
    # that was already successfully written above.
    accent_color = "6b7280"  # default
    try:
        palette = (plan.get("design_spec") or {}).get("tokens", {}).get("color", {})
        primary = palette.get("primary", {})
        accent_color = (primary.get("500") or "6b7280").lstrip("#")
    except Exception:
        pass
    try:
        bundle_illustrations_for_schema(output_dir, schema_dict, accent_color=accent_color)
    except Exception:
        logger.exception(
            "[Schema] illustration bundling failed for %s — schema already written, continuing",
            slug,
        )


async def _generate_schema_for_page(
    plan: dict,
    page: dict,
    slug: str,
    domain_context: dict | None,
    max_retries: int = 3,
    output_dir: str | None = None,
    revise_notes: str | None = None,
) -> dict:
    """LLM call. Returns a validated Page schema dict.

    revise_notes: optional Sprint-3 REVISE block from the page critic.
        When present, prepended to the prompt as an explicit "fix these
        gaps" directive so the second Designer turn addresses the
        critic's findings.
    """
    # Construct the page brief the prompt builder expects.
    page_brief = {
        "route": page.get("route", f"/{slug}"),
        "role": page.get("role") or "",
        "archetype": page.get("archetype") or page.get("type") or "generic",
        # New: page_type drives template_for() injection in build_schema_prompt.
        "page_type": page.get("type") or "generic",
    }
    # Inject the focal entity into the plan for the prompt's binding-context block.
    entity_name = page.get("entity")
    entity_def = (plan.get("entities") or {}).get(entity_name) if entity_name else None
    page_plan = {
        **plan,
        "page_type": page.get("type") or "generic",
        "entity": {"name": entity_name, **(entity_def or {})} if entity_def else {},
        "page": page,
    }
    domain = (
        plan.get("domain")
        or (domain_context or {}).get("domain")
        or "general"
    )
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain=domain,
                                 design_spec=plan.get("design_spec"))
    if domain_context:
        prompt = f"Domain context: {json.dumps(domain_context)}\n\n{prompt}"

    # ── Entity summary context for entity-free pages (dashboards, etc.) ──
    # When a page has no focal entity but does have entity_summary, inject
    # the list so the LLM produces domain-specific labels rather than
    # generic "TOTAL ITEMS" / "Recent Items" placeholders.
    entity_summary = page.get("entity_summary") or []
    if entity_summary and not entity_name:
        _entities_raw = plan.get("entities") or {}
        _entity_details: list[str] = []
        for _en in entity_summary:
            _ed = _entities_raw.get(_en) if isinstance(_entities_raw, dict) else None
            if _ed:
                _fields = [f.get("name", "") for f in (_ed.get("fields") or []) if isinstance(f, dict)][:6]
                _entity_details.append(f"  - {_en} (fields: {', '.join(_fields)})" if _fields else f"  - {_en}")
            else:
                _entity_details.append(f"  - {_en}")
        prompt = (
            f"## Dashboard entity context\n"
            f"This dashboard aggregates data from these entities:\n"
            + "\n".join(_entity_details)
            + "\n\nUse these entity names in dataSources (e.g. entity: \"LeaveRequest\") "
            "and produce domain-specific metric labels (e.g. \"Total Leave Requests\", "
            "\"Pending Approvals\", \"Leave Balance\") — not generic placeholders.\n\n"
            + prompt
        )

    # ── The maquette as INPUT, not as an after-the-fact rewrite ─────────
    # Maquettes are authored in the bootstrap band, so the design for
    # this page already exists on disk by the time we get here. It used
    # to be read only in post-generation, where a composer overwrote
    # whatever this agent produced — the design was decided, ignored,
    # then imposed. Handing it over now means the author builds the
    # right thing the first time and keeps ownership of the result.
    try:
        from services.maquette_brief import build_maquette_brief
        _maq_block = build_maquette_brief(
            output_dir, page_brief["route"], page.get("type"))
        if _maq_block:
            prompt = _maq_block + "\n" + prompt
    except Exception as _maq_exc:  # noqa: BLE001
        logger.debug("[page-schema] maquette brief skipped: %s", _maq_exc)

    # ── IRF-M4-T1: per-route substrate context ──────────────────────────
    # Prepend a hard-constraint block naming the effective shape at this
    # route (plan.app_shape merged with the owning ArchetypeInstance's
    # local_shape) + the owning module's capabilities + plan.runtime_context.
    # Silent no-op when the plan carries no app_shape / no archetypes —
    # historic behavior preserved for pre-substrate plans.
    try:
        from services.route_shape_directive import build_directive as _shape_dir
        _shape_block = _shape_dir(plan, page_brief["route"])
        if _shape_block:
            prompt = _shape_block + "\n\n" + prompt
    except Exception:  # noqa: BLE001 — best-effort
        logger.debug("[route-shape-directive] skipped (assembly failed)")

    # ── Design Context Pack (Sprint 1 of "Forge Great Again") ──
    # Prepend a designer-facing block ABOVE the encyclopedic technical
    # contracts, so the model reads the design intent (page purpose, brief,
    # signature moves, curated component palette) BEFORE the props/tokens
    # rules. Reframes authoring from "fill widget slots" to "design a page".
    #
    # Gated on FORGE_DESIGN_CONTEXT_PACK; scoped to dashboards in slice 1.
    # Silent on failure — the base prompt still runs.
    #
    # Sprint 2 co-signal: when the pack fires we set `_dcp_applied` so the
    # emitted schema can carry a `_designer_authored` marker downstream.
    # Post-gen "top-up" guards (dashboard_completeness, surface_wrap_guard)
    # skip pages that carry the marker — trusting the Designer instead of
    # deterministically rewriting the composition.
    _dcp_applied = False
    try:
        from services.design_context_pack import build_design_context_pack
        _dcp = build_design_context_pack(plan, page, output_dir)
        if _dcp:
            prompt = _dcp + "\n\n" + prompt
            _dcp_applied = True
    except Exception:  # noqa: BLE001 — pack is best-effort
        logger.debug("[design-context-pack] skipped (assembly failed)")

    # Sprint 3 REVISE block — when the page critic found HIGH-severity
    # gaps on the first turn, we re-run generation with the critic's
    # notes prepended. The Designer's second attempt reads the gaps
    # before any technical contracts and rewrites the page to address
    # them. One round only (enforced by the caller in run_page_schema_agent).
    if revise_notes:
        prompt = revise_notes + "\n\n" + prompt

    # ── Action buttons directive ──
    # Inject the declared action buttons (Delete/Approve/New/...) so the model
    # renders a button with each exact label in the right place. The binding
    # pass can only wire buttons the page actually contains.
    _actions_directive = build_actions_directive(page)
    if _actions_directive:
        prompt = prompt + "\n\n" + _actions_directive

    # ── Existing-workflow catalog (context engine) ──
    # Hand the model the REAL domain workflows already generated for this app so
    # it references them by exact name instead of inventing dead refs like
    # `confirmAppointment`. The deterministic binding pass is the safety net; this
    # closes the gap at the source. Best-effort — never block on it.
    if output_dir:
        try:
            from services.context_assembler import workflow_catalog_block
            _wf_catalog = workflow_catalog_block(output_dir)
            if _wf_catalog:
                prompt = prompt + "\n\n" + _wf_catalog
        except Exception:
            pass

        # ── Binding contract (reality, fed forward) ──
        # Hand the page agent the EXACT FK-dropdown / workflow bindings derived
        # from the extracted registry, so it references the real entity
        # ("MembershipPlan") instead of guessing a short name ("Plan").
        try:
            from services.binding_contract import binding_contract_block
            _bind = binding_contract_block(output_dir, entity_name)
            if _bind:
                prompt = prompt + "\n\n" + _bind
        except Exception:
            pass

        # ── Closed resource set + bind-only instruction (Slice 2) ──
        # Hand the model the CLOSED set of REAL registered resources — entity
        # slugs (with columns/types/FKs) and workflow ids (with input columns +
        # trigger) — so it binds UI to resources that exist instead of inventing
        # names. The binding gate (Slice 1) is the safety net; this closes the
        # gap at the source. Additive + best-effort — never block on it.
        try:
            from services.resource_registry_context import (
                build_resource_context,
                build_resource_context_slice,
            )
            # Enterprise scale (B1): bound the block to the page's focal entity
            # (its columns + FK-neighbors + workflows targeting it) instead of the
            # whole app — O(pages × app-size) is the primary scale bottleneck.
            # An entity-less page (dashboard/report) legitimately spans entities,
            # so it keeps the whole-app context. The slice itself falls back to
            # whole-app on a missing registry / unknown entity.
            if entity_name:
                _resources = build_resource_context_slice(output_dir, entity_name)
            else:
                _resources = build_resource_context(output_dir)
            if _resources:
                prompt = prompt + "\n\n" + _resources
        except Exception:
            pass

    # ── Product standards (frontend + completeness + content) ──
    # Same canonical rubric the design agent sees, scoped to what the
    # page-schema agent actually authors (component choice, empty/loading/
    # error states, real bindings, domain-specific copy). Post-gen guards
    # + Self-Verify Pass are the safety net; this closes the gap at the
    # source so fewer defects reach them.
    try:
        from services.product_standards import render_for as _standards_for
        from services.taste_standards import render_for as _taste_for
        _standards = _standards_for("page_schema")
        if _standards:
            prompt = prompt + "\n\n" + _standards
        # Design stance — ONE chosen stance, never a menu, so the same app
        # cannot average across soft/minimalist/brutalist. A missing brief
        # degrades to the default stance; it never fails the page.
        try:
            from services.design_brief_to_prompt import load_brief_from_disk
            _brief = load_brief_from_disk(str(output_dir))
        except Exception:
            _brief = None
        _taste = _taste_for("page_schema", _brief)
        if _taste:
            prompt = prompt + "\n\n" + _taste
    except Exception:
        pass

    # ── Shell-aware content-only instruction ──
    # When shell.json exists in the output dir AND this page is not an auth
    # page, instruct the LLM to emit content-only — no top-nav, no sidebar,
    # no app-name header. Those come from the shell.
    _page_type_for_shell = (page.get("type") or "").lower()
    _shell_path = Path(output_dir) / "src" / "schemas" / "shell.json" if output_dir else None
    if _shell_path and _shell_path.exists() and _page_type_for_shell != "auth":
        _shell_note = (
            "\n\n## IMPORTANT: App shell context — STRICT RULES\n"
            "This page renders INSIDE a shared app shell (shell.json) that already "
            "provides the sidebar navigation, top header bar, app logo/name, and user menu.\n\n"
            "### FORBIDDEN — never emit these nodes in a page schema:\n"
            "- Any node with type Hero at the root or top level (a full-width hero banner "
            "with headline + subtitle + CTA is shell chrome, not page content)\n"
            "- Sidebar navigation (Stack/Container of Button[variant=ghost] nav links)\n"
            "- App name / logo text at the top\n"
            "- User avatar menu or notification bell at the top\n"
            "- Any Row/Container with data-shell-region, className containing 'sidebar', "
            "'topbar', 'navbar', or 'header' at the root level\n\n"
            "### REQUIRED structural rule:\n"
            "Your schema's root MUST be a Stack or Container node. "
            "Its first child must be a page-level heading (Heading or Row with a Heading) "
            "that names the current page — never a navigation bar, hero banner, or shell-level element.\n\n"
            "### Good example root:\n"
            '{ "type": "Stack", "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" }, '
            '"children": [{ "type": "Heading", "props": { "content": "Leave Requests", "level": 1 } }, ...rest of page content] }\n\n'
            "### Bad example root (FORBIDDEN):\n"
            '{ "type": "Hero", "props": { "headline": "...", "subhead": "...", "ctas": [...] } }\n\n'
            "Omit any node that would duplicate the shell's chrome.\n"
        )
        prompt = prompt + _shell_note

    last_error: str | None = None
    schema_dict: dict | None = None
    for attempt in range(max_retries + 1):
        retry_suffix = (
            f"\n\nPrevious attempt failed validation:\n{last_error}\n"
            "Fix the issue and output the corrected JSON."
            if last_error else ""
        )
        try:
            # Cache the base prompt so validation-retry attempts reuse it.
            from services.sdk_agent_runner import with_cache_prefix
            raw_text = await _collect_llm_text(with_cache_prefix(prompt, retry_suffix))
        except Exception as exc:  # noqa: BLE001 — classify, then route
            from services.chunked_schema import is_output_overflow_error
            if is_output_overflow_error(exc):
                break  # too large for one response — go straight to chunked
            last_error = f"LLM error: {exc}"
            continue
        schema_dict = _extract_json(raw_text)
        if schema_dict is None:
            last_error = f"Could not parse JSON: {raw_text[:200]}"
            continue
        schema_dict = normalize_v2_schema(schema_dict)
        if (err := _validate_schema_json(schema_dict)) is not None:
            last_error = err
            continue
        # Sprint 2 marker — stamped on every schema whose authoring turn
        # was primed by the Design Context Pack. Downstream guards read
        # it to know "this composition came from a designer, not a slot-
        # fill; don't overwrite".
        if _dcp_applied and isinstance(schema_dict, dict):
            schema_dict["_designer_authored"] = True
        # IRF-M5-T7 — domain conformance verify pass. Silent record into
        # SessionContext.verify_history (M5-T2 ambient) when a context is
        # set. Flag-gated in stage_verify_ladder — off by default keeps
        # generation behavior unchanged (record-only telemetry).
        try:
            from services.stage_verify_ladder import run_page_ladder
            run_page_ladder(
                stage_name="page_schema_agent",
                plan=plan,
                route=page.get("route") or f"/{slug}",
                attempt_1=lambda: schema_dict,
            )
        except Exception:  # noqa: BLE001 — never let telemetry abort generation
            logger.debug("[verify-ladder] skipped (assembly failed)")
        # IRF-M5-T8 — multi-perspective critic panel (design + ux +
        # correctness). Records one VerifyRecord per persona to the
        # ambient SessionContext. Flag-gated in critic_panel — off by
        # default is record-only (needs_revise stays False so caller
        # keeps historic behavior). REVISE-loop firing on failed
        # personas is a M6-T8 upgrade.
        try:
            from services.critic_panel import run_panel as _critic_run_panel
            _critic_run_panel(
                schema_dict, plan,
                page.get("route") or f"/{slug}",
                stage="page_schema_agent",
            )
        except Exception:  # noqa: BLE001
            logger.debug("[critic-panel] skipped (assembly failed)")
        return schema_dict

    # Single-call path overflowed or exhausted retries → try chunked generation
    # (skeleton + per-region fills) before giving up to the minimal fallback.
    from services.chunked_schema import generate_chunked_schema
    try:
        chunked = await generate_chunked_schema(
            prompt, {"id": slug, "route": page.get("route", f"/{slug}")}, _collect_llm_text
        )
    except Exception:  # noqa: BLE001 — never let chunking abort generation
        chunked = None
    if chunked is not None:
        chunked = normalize_v2_schema(chunked)
        if _validate_schema_json(chunked) is None:
            if _dcp_applied and isinstance(chunked, dict):
                chunked["_designer_authored"] = True
            return chunked

    _fallback = schema_dict or _minimal_schema(slug, page.get("type", "generic"))
    if _dcp_applied and isinstance(_fallback, dict):
        _fallback["_designer_authored"] = True
    return _fallback


# Re-use helpers from feature_slice_schema_agent rather than fork.
# The page schema agent additionally registers the illustrations MCP server
# so the LLM can pick unDraw assets during generation.
async def _collect_llm_text(prompt: str) -> str:
    """Per-page schema generation on the Anthropic SDK (reliable, ~seconds each) instead
    of the bundled CLI, which crawls under subscription-auth throttle. Drops the
    illustrations MCP (the visual enricher fills photoUrl/icon separately, so pages still
    render fully). Falls back to the bundled-CLI shared path when no API key is set."""
    import os
    import asyncio

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        from agents.feature_slice_schema_agent import _collect_llm_text as _shared
        return await _shared(
            prompt,
            mcp_servers={_ILLUSTRATIONS_SERVER_NAME: _get_illustrations_mcp_config()},
            allowed_tools=_ILLUSTRATIONS_ALLOWED_TOOLS,
            max_turns=6,
        )

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    client = llm_client.AsyncAnthropic(api_key=api_key)
    msg = await asyncio.wait_for(
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system="You generate JSON schemas. Output ONLY a single JSON object.",
            messages=[{"role": "user", "content": prompt}],
        ),
        timeout=180,
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def _extract_json(text: str):
    from agents.feature_slice_schema_agent import _extract_json as _shared
    return _shared(text)


def _validate_schema_json(schema_dict: dict):
    from agents.feature_slice_schema_agent import _validate_schema_json as _shared
    return _shared(schema_dict)


def _minimal_schema(slug: str, page_type: str) -> dict:
    return {
        "schemaVersion": "2",
        "id": slug,
        "route": f"/{slug}" if slug != "home" else "/",
        "layout": "main",
        "root": {
            "type": "Stack",
            "id": "root",
            "children": [{
                "type": "Heading",
                "id": "title",
                "props": {"level": 1, "content": page_type.capitalize()},
            }],
        },
    }

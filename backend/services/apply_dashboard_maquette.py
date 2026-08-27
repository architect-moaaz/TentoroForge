"""Post-gen: rebuild the dashboard schema from the persisted maquette.

Runs AFTER page authoring. Reads
``<output>/src/contracts/dashboard-maquette.json`` (written by the
maquette LLM step in the pipeline) and rewrites the dashboard page
schema deterministically:

  * KPIs → MetricTile row bound to real `op:"count"` / `op:"sum"` dataSources
  * Primary chart → Chart bound to `op:"series"` with the maquette's
    entity + group_by + aggregate
  * Activity → ActivityFeed bound to entity `orderBy: createdAt desc`
  * Hero → Hero header with photoUrl + a greeting line

This is the "authority not advisory" seam — no LLM in the assembly.
The maquette IS the content contract; the assembler is mechanical.

Idempotent: rewriting an already-maquette-driven schema is a no-op.
Fails closed: any exception logs and leaves the existing schema
untouched.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# Filename-slugs the pipeline uses for the dashboard schema. First match wins.
# NOTE: this is a fallback only — the primary lookup goes through the plan's
# ``pages`` list and picks whichever page has ``type=dashboard`` regardless
# of its route (a plan can name its dashboard ``/admin`` or ``/dispatch`` etc).
_DASHBOARD_SLUGS = ("dashboard", "home", "index", "overview", "member-dashboard",
                    "admin-dashboard", "instructor-dashboard")

# Marker so we don't reapply on an already-composed dashboard.
_MARKER_META_KEY = "maquette_composed"


def apply_maquette_to_dashboard(output_dir: str) -> dict[str, Any]:
    """Rebuild the dashboard page schema from the persisted maquette.

    Returns a diagnostic dict::

        {"applied": bool, "schema_path": str|None, "reason": str,
         "sections_written": int}

    Never raises. The caller (a post-gen orchestrator) can log the
    diagnostic and move on.

    Phase 3 (Dashboard Authority) — the composer is the SOLE writer for
    dashboards when :func:`services.dashboard_authority.is_dashboard_authority_enabled`
    is on. Two extensions activate under that flag:

    1. **Bootstrap the schema when it doesn't exist.** The LLM
       ``page_schema_agent`` skips dashboards under the flag, so the
       target file may not be on disk yet. Derive its path from
       ``plan.json`` and treat missing as "empty existing schema".

    2. **Recipe fallback when the maquette JSON is missing.** When the
       LLM maquette-authoring step failed (timeout / bad output),
       write a bootstrap skeleton then invoke
       :func:`services.dashboard_completeness.apply_dashboard_completeness`
       to fill it with the recipe library's minimum-viable content set.
    """
    root = Path(output_dir)
    _authority_on = _is_authority_enabled()
    maq_path = root / "src" / "contracts" / "dashboard-maquette.json"

    if not maq_path.is_file():
        if _authority_on:
            return _fallback_via_completeness(root, reason="no maquette on disk")
        return {"applied": False, "schema_path": None,
                "reason": "no maquette on disk", "sections_written": 0}

    try:
        maquette = json.loads(maq_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[dashboard-maquette] unreadable: %s", exc)
        if _authority_on:
            return _fallback_via_completeness(
                root, reason=f"maquette unreadable: {exc}"
            )
        return {"applied": False, "schema_path": None,
                "reason": f"maquette unreadable: {exc}", "sections_written": 0}

    schema_path = _find_dashboard_schema(root)
    _bootstrapped = False
    if schema_path is None:
        if _authority_on:
            # Authority flag on + LLM agent skipped the dashboard → the file
            # simply isn't on disk yet. Derive the target path from the plan
            # and proceed with an empty ``existing`` skeleton so the composer
            # writes fresh.
            schema_path = _bootstrap_target_path(root)
            if schema_path is None:
                return {"applied": False, "schema_path": None,
                        "reason": "no dashboard route in plan.pages",
                        "sections_written": 0}
            _bootstrapped = True
        else:
            return {"applied": False, "schema_path": None,
                    "reason": "no dashboard schema found", "sections_written": 0}

    if _bootstrapped:
        # No file on disk — treat as empty existing schema. Composer writes
        # its own id/route/layout below.
        existing: dict = {}
    else:
        try:
            existing = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard-maquette] schema unreadable %s: %s", schema_path, exc)
            return {"applied": False, "schema_path": str(schema_path),
                    "reason": f"schema unreadable: {exc}", "sections_written": 0}

    # Idempotency: skip if already composed by this pass.
    if isinstance(existing, dict) and isinstance(existing.get("meta"), dict):
        if existing["meta"].get(_MARKER_META_KEY) is True:
            return {"applied": False, "schema_path": str(schema_path),
                    "reason": "already composed from maquette", "sections_written": 0}

    # This guard used to be BOOTSTRAP-ONLY, on the assumption that the
    # maquette reaches the page AUTHOR as a design brief
    # (services.maquette_brief) and the author therefore builds the
    # dashboard from it — so rewriting here would discard the author's work.
    #
    # Measured across the 223-app corpus, that assumption does not hold. Of
    # the 125 apps with a dashboard, 43 shipped with no chart at all, and of
    # the 10 chartless ones that DID have a maquette, every single one
    # declared a fully-specified primary_chart — entity, group_by, aggregate,
    # window, help text. "Bills by Legislative Stage". "Bookings Over the Past
    # Month". The deciding step ran, produced good domain judgment, and the
    # authored page simply did not carry it.
    #
    # So under the authority flag this module is what it already says it is in
    # its own docstring: the SOLE writer for dashboards. The flag exists
    # precisely to make one writer per artifact real, and yielding to a second
    # writer is the thing it was built to stop.
    #
    # Two protections stay. The idempotency marker above still short-circuits
    # a second compose, and Smith/user re-applies never reach here at all —
    # the post-gen caller gates this whole block on ``not force`` for exactly
    # that reason (BUG-APPLY-1, "my edit never saved").
    _authority = _is_authority_enabled()
    if (not _bootstrapped and not _authority
            and isinstance(existing, dict) and existing.get("root")):
        return {"applied": False, "schema_path": str(schema_path),
                "reason": "page already authored — not overwriting",
                "sections_written": 0}


    root_id = existing.get("id") or "dashboard"
    route = existing.get("route") or "/dashboard"

    # CREATIVE-6b — LLM page composer early-exit. See the sibling hooks in
    # apply_collection_maquette / apply_record_maquette for the pattern.
    # Fall through to deterministic assembly on any failure.
    try:
        from services.page_composer_pipeline import (
            compose_page_via_pipeline_sync as _llm_compose,
            is_flag_on as _llm_flag_on,
            page_from_maquette as _page_from_maquette,
            _write_page_schema as _llm_write,
        )
        if _llm_flag_on():
            _plan_path = root / "src" / "contracts" / "plan.json"
            _plan = json.loads(_plan_path.read_text(encoding="utf-8")) \
                if _plan_path.is_file() else {}
            # Dashboard maquette carries no explicit route/entity — use the
            # resolved route from the on-disk schema (or /dashboard fallback)
            # and let entity be empty (dashboards mix entities).
            _mq_for_page = dict(maquette) if isinstance(maquette, dict) else {}
            _mq_for_page.setdefault("route", route)
            _page = _page_from_maquette(_mq_for_page, _plan, "dashboard")
            from services.page_vocabulary import _load_brief as _lb
            _llm_schema, _llm_prov = _llm_compose(
                _page, _plan, root, brief=_lb(root))
            if _llm_schema is not None:
                # Maquette-fidelity top-up: the LLM composer often authors a
                # subset of the maquette (e.g. two charts) and drops the KPI
                # strip, activity feed, or hero band. Inject the missing
                # pillars deterministically before writing so the shipped
                # page honors what the planner actually asked for.
                _topup = _topup_missing_pillars(_llm_schema, maquette)
                _wrote = _llm_write(_page, _llm_schema, root)
                if _wrote is not None:
                    return {"applied": True, "schema_path": str(_wrote),
                            "reason": f"ok (llm-composed; topped-up: {_topup})",
                            "sections_written": len(
                                (_llm_schema.get("root") or {}).get("children") or []
                            )}
    except Exception as _llm_exc:  # noqa: BLE001
        logger.debug("[dashboard-maquette] llm composer skipped: %s", _llm_exc)

    sections, data_sources = _build_sections(maquette)
    if not sections:
        return {"applied": False, "schema_path": str(schema_path),
                "reason": "maquette produced no sections", "sections_written": 0}

    # ── Moments layer: section_rhythm + signature_moves ──
    # section_rhythm maps to Stack gap so wellness/editorial apps get
    # breathing room and admin/fintech apps get density. Default is
    # "cozy" = spacing.6, matching the pre-Phase-2 behaviour.
    _rhythm = maquette.get("section_rhythm") if isinstance(maquette.get("section_rhythm"), str) else "cozy"
    _gap_token = {
        # "tight" floors at 16px: 12px between full page sections (serif h2s,
        # carded KPI rows, charts) read as cramped on every live review —
        # density should come from within widgets, not from fusing sections.
        "tight": "tokens.spacing.4",
        "cozy": "tokens.spacing.6",
        "generous": "tokens.spacing.10",
    }.get(_rhythm, "tokens.spacing.6")

    root_props: dict[str, Any] = {"gap": _gap_token}
    # Signature moves flow as data attributes so downstream design
    # critics and renderer variants can key off them without a schema
    # shape change. LLM-authored ids are catalog-validated in a
    # separate pass (services.signature_move_resolver).
    _sig_moves = maquette.get("signature_moves") or []
    _sig_moves = [s for s in _sig_moves if isinstance(s, str) and s.strip()]
    if _sig_moves:
        root_props["data-signature-move"] = " ".join(_sig_moves[:8])

    # Preserve existing schemaVersion + layout if present, else set defaults.
    new_schema: dict = {
        "schemaVersion": existing.get("schemaVersion", "2"),
        "id": root_id,
        "route": route,
        "layout": existing.get("layout", "main"),
        "root": {
            "type": "Stack",
            "props": root_props,
            "children": sections,
        },
    }
    if data_sources:
        new_schema["dataSources"] = data_sources

    # Preserve/extend meta with our marker.
    prev_meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    new_schema["meta"] = {**prev_meta, _MARKER_META_KEY: True}

    try:
        # Bootstrap path may need to create the schemas directory.
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        # Strip Phase 2 metadata (data-*, style) out of every node's
        # props — the renderer's schemas are .strict() and would log a
        # validation warning for each key. See composer_prop_hygiene.
        from services.composer_prop_hygiene import sanitize_schema as _sanitize
        _sanitize(new_schema)
        schema_path.write_text(json.dumps(new_schema, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[dashboard-maquette] write failed %s: %s", schema_path, exc)
        return {"applied": False, "schema_path": str(schema_path),
                "reason": f"write failed: {exc}", "sections_written": 0}

    logger.info(
        "[dashboard-maquette] composed %s from maquette — %d sections%s",
        schema_path.name, len(sections),
        " (bootstrap)" if _bootstrapped else "",
    )
    return {"applied": True, "schema_path": str(schema_path),
            "reason": "ok (bootstrap)" if _bootstrapped else "ok",
            "sections_written": len(sections)}


# ─────────────────────────── authority helpers ─────────────────────────


def _is_authority_enabled() -> bool:
    """Import-safe check for the Phase 3 dashboard authority flag.

    Kept as a helper (rather than a module-level constant) so tests can
    flip the env var and the change takes effect on the next call. Any
    import failure defaults to False — safety: existing behaviour is
    the fall-through path.
    """
    try:
        from services.dashboard_authority import is_dashboard_authority_enabled
        return is_dashboard_authority_enabled()
    except Exception:  # noqa: BLE001
        return False


def _bootstrap_target_path(root: Path) -> Optional[Path]:
    """Derive the target schema path for the plan's landing dashboard.

    Reuses the plan-driven ranking that :func:`_find_dashboard_schema`
    uses (landing routes first, then any dashboard-typed page). Returns
    ``None`` when no dashboard-typed page exists — the composer signals
    that upstream so the caller can log a coherent skip reason.
    """
    plan_path = root / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return None
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    _tier0: list[str] = []
    _tier1: list[str] = []
    _tier2: list[str] = []
    _landing = {"/dashboard", "/home", "/overview", "/"}
    for page in plan.get("pages") or []:
        if not isinstance(page, dict):
            continue
        if str(page.get("type", "")).lower() != "dashboard":
            continue
        r = page.get("route")
        if not (isinstance(r, str) and r.startswith("/")):
            continue
        r_norm = r.rstrip("/") or "/"
        if r_norm in _landing:
            _tier0.append(r)
        elif r_norm.endswith("/dashboard") or r_norm.endswith("/overview"):
            _tier1.append(r)
        else:
            _tier2.append(r)

    for route in (_tier0 + _tier1 + _tier2):
        # Same slug convention _find_dashboard_schema uses: strip slashes,
        # ``/`` maps to ``dashboard.json``.
        stripped = route.strip("/") or "dashboard"
        return root / "src" / "schemas" / f"{stripped}.json"
    return None


def _fallback_via_completeness(root: Path, *, reason: str) -> dict[str, Any]:
    """When the maquette is missing under the authority flag, bootstrap
    a minimal skeleton then let :mod:`services.dashboard_completeness`
    fill it with the recipe library's default content set.

    Always returns a diagnostic dict — never raises. When even the
    bootstrap can't identify a target route, returns applied=False with
    a coherent reason.
    """
    schema_path = _bootstrap_target_path(root)
    if schema_path is None:
        return {"applied": False, "schema_path": None,
                "reason": f"{reason} + no dashboard route in plan.pages",
                "sections_written": 0}
    # Emit a bare-bones skeleton (no marker → completeness will top it up).
    stub: dict[str, Any] = {
        "schemaVersion": "2",
        "id": schema_path.stem,
        "route": "/" + schema_path.stem if schema_path.stem != "dashboard" else "/dashboard",
        "layout": "main",
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": []},
    }
    try:
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(stub, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"applied": False, "schema_path": str(schema_path),
                "reason": f"{reason} + skeleton write failed: {exc}",
                "sections_written": 0}
    # Let the completeness recipe fill it.
    try:
        from services.dashboard_completeness import apply_dashboard_completeness
        dc = apply_dashboard_completeness(str(root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[dashboard-maquette] completeness fallback failed: %s", exc)
        return {"applied": False, "schema_path": str(schema_path),
                "reason": f"{reason} + completeness fallback failed: {exc}",
                "sections_written": 0}
    return {"applied": True, "schema_path": str(schema_path),
            "reason": f"fallback-via-completeness ({reason})",
            "sections_written": int(dc.get("sections_added", 0))}


# ─────────────────────────── schema assembly ───────────────────────────


def _find_dashboard_schema(root: Path) -> Optional[Path]:
    """Find the dashboard schema. Tries in order:

    1. **Plan-driven** — read ``plan.pages`` and pick the entry whose
       ``type == "dashboard"``. Turn its route into a schema-file slug and
       locate the file. This is the authoritative match — plans can name
       their dashboards ``/admin`` or ``/dispatch`` and we still find them.
    2. Well-known filename slugs (``dashboard.json`` / ``home.json`` / …).
    3. Any schema whose ``route`` matches a known dashboard route.
    """
    schema_dirs = [
        root / "src" / "schemas",
        root / "src" / "contracts" / "pages",
        root / "schemas" / "pages",
    ]

    # ── Pass 1: plan-driven ────────────────────────────────────────────
    # Priority order — the maquette is a single "landing" content spec and
    # we must apply it to the primary landing dashboard, not a role/domain
    # variant. Plans commonly declare 2-3 dashboard-typed pages (e.g.
    # /admin/analytics, /dashboard, /classes) and taking the first-seen
    # picks the wrong one when /classes precedes /dashboard in plan order.
    #
    # Rank order (lower = earlier applied):
    #   0. exact landing routes: /dashboard, /home, /overview, /
    #   1. any route ending in /dashboard or /overview (e.g. /admin/dashboard)
    #   2. other dashboard-typed pages in plan order
    plan_path = root / "src" / "contracts" / "plan.json"
    dashboard_routes: list[str] = []
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            _tier0: list[str] = []
            _tier1: list[str] = []
            _tier2: list[str] = []
            _landing = {"/dashboard", "/home", "/overview", "/"}
            for page in plan.get("pages") or []:
                if not isinstance(page, dict):
                    continue
                if str(page.get("type", "")).lower() != "dashboard":
                    continue
                r = page.get("route")
                if not (isinstance(r, str) and r.startswith("/")):
                    continue
                r_norm = r.rstrip("/") or "/"
                if r_norm in _landing:
                    _tier0.append(r)
                elif r_norm.endswith("/dashboard") or r_norm.endswith("/overview"):
                    _tier1.append(r)
                else:
                    _tier2.append(r)
            dashboard_routes = _tier0 + _tier1 + _tier2
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard-maquette] plan read failed: %s", exc)

    def _route_to_slugs(route: str) -> list[str]:
        """Candidate file slugs for a route, best first.

        Every route but the root names its own file. The root has no name,
        and pipelines disagree about what to call it — `dashboard.json` is
        the renderer convention, but the page emitters write `home.json`,
        and some write `index.json`. Returning a single guess meant a real
        landing page under any other name could never be found, and the
        caller then walked on to a *different* dashboard-typed route and
        applied the landing maquette there (live: x4fcmdyi put the landing
        composition on /analytics and left home.json to a top-up guard).
        """
        stripped = route.strip("/")
        if stripped:
            return [stripped]
        return ["dashboard", "home", "index"]

    for base in schema_dirs:
        if not base.is_dir():
            continue
        for route in dashboard_routes:
            for slug in _route_to_slugs(route):
                p = base / f"{slug}.json"
                if p.is_file():
                    return p
                # Also try just the leaf (some pipelines flatten):
                p2 = base / f"{slug.split('/')[-1]}.json"
                if p2.is_file():
                    return p2

    # ── Pass 2: well-known slugs ───────────────────────────────────────
    for base in schema_dirs:
        if not base.is_dir():
            continue
        for slug in _DASHBOARD_SLUGS:
            p = base / f"{slug}.json"
            if p.is_file():
                return p

    # ── Pass 3: content-based match ────────────────────────────────────
    _KNOWN_DASHBOARD_ROUTES = {"/dashboard", "/home", "", "/overview", "/admin"}
    for base in schema_dirs:
        if not base.is_dir():
            continue
        for p in base.glob("**/*.json"):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            # A schema with NO route key stringifies to "" and would match
            # the root entry below — so the first route-less file the glob
            # happened to reach became "the dashboard". Require the key to
            # be present before believing its value.
            if "route" not in doc:
                continue
            route = str(doc.get("route") or "").rstrip("/")
            if route in _KNOWN_DASHBOARD_ROUTES:
                return p
    return None


# ═══════════════════════════════════════════════════════════════════════
# LLM top-up: honor the maquette's substantive pillars when the composer
# authored a subset. The LLM keeps creative freedom for how sections read
# and stack; we guarantee the KPI strip, activity feed, and hero band
# survive the render.
# ═══════════════════════════════════════════════════════════════════════

def _walk_types(node: Any) -> Iterable[str]:
    """DFS yield node.type strings, so callers can spot presence of a
    component anywhere in the tree without hand-rolling a walker."""
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str):
            yield t
        for c in node.get("children") or []:
            yield from _walk_types(c)
    elif isinstance(node, list):
        for c in node:
            yield from _walk_types(c)


def _build_gauge_nodes(gauges: list) -> list[dict]:
    """Turn parsed gauge hints into Gauge / SplitArc widget nodes.

    Each hint has ``{label, kind, min?, max?, target?}`` from
    :func:`services.plan_directive_parser.parse_gauges`. The parser can't
    know which dataSource feeds a specific gauge — we emit a static
    zero-value placeholder that the runtime renders visibly until a real
    binding is wired. That keeps the widget on screen (proof the user's
    requirement landed) rather than silently dropped.

    Shapes must match the library exports (packages/library/src/components):
      * ``Gauge`` — takes ``{value, min, max, label, unit?, thresholds?}``.
        Radial 270° arc with a needle at the current value.
      * ``SplitArc`` — takes ``{segments: [{label, value, color,
        endLabel?, trend?}, ...], title?, total?, size?}``. Half-arc split
        across N coloured segments. NOT the same shape as Gauge.
    """
    out: list[dict] = []
    for g in gauges:
        if not isinstance(g, dict) or not g.get("label"):
            continue
        kind = (g.get("kind") or "").lower()
        node_type = "SplitArc" if kind == "splitarc" else "Gauge"
        label = str(g["label"])
        if node_type == "Gauge":
            props: dict[str, Any] = {
                "label": label,
                "value": 0,  # static placeholder; real binding wired later
            }
            if g.get("min") is not None:
                props["min"] = g["min"]
            if g.get("max") is not None:
                props["max"] = g["max"]
            # `unit` renders inline with the readout — "%" for rate/retention
            # style metrics keeps the readout self-explanatory even at 0.
            if "rate" in label.lower() or "retention" in label.lower() \
                    or "percent" in label.lower() or "%" in label:
                props["unit"] = "%"
            # `thresholds` gives the arc colored zones. Emit a sensible
            # green-amber-red band across the range so the empty gauge
            # doesn't render as monochrome grey. Omit when no min/max.
            _lo = props.get("min", 0)
            _hi = props.get("max", 100)
            _span = _hi - _lo
            if _span > 0:
                props["thresholds"] = [
                    {"value": _lo + _span * 0.5, "color": "var(--color-danger-500, #ef4444)"},
                    {"value": _lo + _span * 0.8, "color": "var(--color-warning-500, #f59e0b)"},
                    {"value": _hi,               "color": "var(--color-success-500, #10b981)"},
                ]
        else:
            # SplitArc: segments contract. Show `achieved` vs `remaining`
            # so the arc renders as two visible half-slices even at 0.
            _target = float(g.get("target") or 100)
            _actual = 0.0  # placeholder until a real binding is wired
            _remaining = max(_target - _actual, _target * 0.001)  # non-zero so arc shows
            props = {
                "title": label,
                "segments": [
                    {"label": "Achieved",  "value": _actual,   "color": "var(--color-primary-500, #3b82f6)", "endLabel": str(int(_actual))},
                    {"label": "Remaining", "value": _remaining, "color": "var(--color-border-default, #e2e8f0)", "endLabel": str(int(_target))},
                ],
                "total": _target,
            }
        out.append({"type": node_type, "props": props})
    return out


def _topup_missing_pillars(schema: dict, maquette: dict) -> str:
    """Inject missing maquette pillars into an LLM-composed schema.

    Detects which of {kpis, activity, hero} the maquette declared, walks
    the LLM output for their signature components (MetricTile, ActivityFeed,
    hero-band type), and appends missing pillars using the same builder
    helpers the deterministic path uses. Also merges required dataSources.

    Returns a comma-separated summary of what was added (empty string when
    the LLM already covered everything). Idempotent — running twice on the
    same schema is a no-op.
    """
    if not isinstance(schema, dict) or not isinstance(maquette, dict):
        return ""
    root = schema.get("root")
    if not isinstance(root, dict):
        return ""
    children = root.setdefault("children", [])
    if not isinstance(children, list):
        return ""

    existing_types = set(_walk_types(root))
    ds_list = schema.setdefault("dataSources", [])
    if not isinstance(ds_list, list):
        ds_list = []
        schema["dataSources"] = ds_list
    used_names: set[str] = set()
    for d in ds_list:
        if isinstance(d, dict) and isinstance(d.get("name"), str):
            used_names.add(d["name"])

    added: list[str] = []

    # Hero — prepend so it sits at the top of the page.
    hero = maquette.get("hero")
    if isinstance(hero, dict) and "Hero" not in existing_types:
        # Presence heuristic: hero builder emits a section with a Heading
        # containing the greeting text. We inject when there's no dedicated
        # hero band AND the LLM's first section isn't already a Heading
        # carrying similar copy.
        greeting = str(hero.get("greeting") or "").strip()
        first_type = children[0].get("type") if children and isinstance(children[0], dict) else ""
        first_content = ""
        if children and isinstance(children[0], dict):
            first_props = children[0].get("props") or {}
            first_content = str(first_props.get("content") or "")
        already_has_hero_like = (
            first_type == "Heading" and greeting and greeting[:20].lower() in first_content.lower()
        )
        if not already_has_hero_like:
            hero_node = _build_hero_node(hero)
            if hero_node is not None:
                children.insert(0, hero_node)
                added.append("hero")

    # KPI strip — insert after the hero (or at index 0/1) so it precedes
    # any charts the LLM authored.
    kpis = maquette.get("kpis") or []
    if kpis and "MetricTile" not in existing_types:
        kpi_children: list[dict] = []
        for i, kpi in enumerate(kpis):
            if not isinstance(kpi, dict):
                continue
            label = kpi.get("label"); entity = kpi.get("entity"); op = kpi.get("op")
            if not (label and entity and op):
                continue
            source_name = _unique_name(f"{entity}_{op}_{i}", used_names)
            ds_props: dict[str, Any] = {"entity": str(entity), "op": str(op)}
            if kpi.get("field"):
                ds_props["field"] = str(kpi["field"])
            if kpi.get("filter"):
                ds_props["filter"] = str(kpi["filter"])
            ds_list.append({"name": source_name, **ds_props})
            fmt = str(kpi.get("format") or "number")
            if fmt not in ("number", "currency", "percent", "duration"):
                fmt = "number"
            kpi_children.append({"type": "MetricTile", "props": {
                "label": str(label),
                "value": f"{{{{{source_name}}}}}",
                "format": fmt,
            }})
        if kpi_children:
            n = len(kpi_children)
            # Grid.tsx reads `columns` (int), NOT `cols` (object). It also
            # generates its own responsive breakpoint classes internally.
            # Emitting `cols: {base,sm,lg}` here silently landed columns=1
            # and every KPI/gauge Grid stacked vertically.
            _columns = 4 if n >= 4 else 3 if n == 3 else 2 if n == 2 else 1
            kpi_grid = {
                "type": "Grid",
                "props": {"gap": "tokens.spacing.4", "columns": _columns},
                "children": kpi_children,
            }
            # Insert after hero if present, else at top
            insert_at = 1 if (children and isinstance(children[0], dict)
                              and children[0].get("type") in ("Hero", "Container")
                              and "hero" in added) else 0
            children.insert(insert_at, {"type": "Heading",
                                        "props": {"content": "Overview", "level": 2}})
            children.insert(insert_at + 1, kpi_grid)
            added.append(f"kpis({n})")

    # Gauges — inject before activity feed. Sourced from
    # ``plan.hints.gauges`` (Slice 1 of requirement-as-central-piece).
    gauges = maquette.get("gauges") or []
    has_gauge = "Gauge" in existing_types or "SplitArc" in existing_types
    if gauges and not has_gauge:
        gauge_nodes = _build_gauge_nodes(gauges)
        if gauge_nodes:
            n = len(gauge_nodes)
            _columns = 3 if n >= 3 else 2 if n == 2 else 1
            children.append({"type": "Heading",
                             "props": {"content": "Health & targets", "level": 2}})
            # `place-items-center` centers each Grid cell's content so
            # widgets with different intrinsic alignment (Gauge uses
            # `items-center`, SplitArc uses `items-stretch min-w-[220px]`)
            # both sit centered in their columns instead of left-anchoring.
            children.append({
                "type": "Grid",
                "props": {
                    "gap": "tokens.spacing.4",
                    "columns": _columns,
                    "className": "place-items-center",
                },
                "children": gauge_nodes,
            })
            added.append(f"gauges({n})")

    # Activity feed — append at the end.
    act = maquette.get("activity")
    if isinstance(act, dict) and act.get("entity") and "ActivityFeed" not in existing_types:
        act_name = _unique_name(f"{act['entity']}_recent", used_names)
        limit = act.get("limit") if isinstance(act.get("limit"), int) else 5
        order_by = act.get("order_by", "createdAt")
        ds_list.append({
            "name": act_name,
            "entity": str(act["entity"]),
            "op": "list",
            "orderBy": str(order_by),
            "orderDir": "desc",
            "limit": int(limit),
        })
        children.append({"type": "Heading",
                         "props": {"content": str(act.get("title", "Recent activity")), "level": 2}})
        children.append({"type": "ActivityFeed",
                         "props": {"dataSource": f"{{{{{act_name}}}}}"}})
        added.append("activity")

    return ", ".join(added)


def _build_chrome_nodes(maquette: dict) -> list[dict]:
    """Section chrome — subtitle + filter bar + reset chip.

    Returns 0-2 nodes to prepend at the top of the page sections:

      1. A subtitle row (Text with muted styling) when
         ``maquette.subtitle`` is set. Emitted as a Text node — the H1
         already lives in the shell breadcrumb / route header so the
         subtitle is body prose beneath it, not another heading.

      2. A filter bar when ``maquette.filters`` is non-empty: a
         FilterBar carrying the select-kind chips (plus a search box for
         a text-kind filter), any date-range pickers, and an optional
         Reset button. FilterBar is what makes the chips real — the page
         only honours URL params it declares filterable, and chip keys
         are that declaration.

    Chrome is purely visual — it does NOT consume data sources.
    """
    nodes: list[dict] = []

    # ── Subtitle ──────────────────────────────────────────────────────
    subtitle = maquette.get("subtitle")
    if isinstance(subtitle, str) and subtitle.strip():
        nodes.append({
            "type": "Text",
            "props": {
                "content":   subtitle.strip(),
                "variant":   "muted",
                # Editorial subtitle — one line under the page header.
                # Bordering ``className`` provides the max-width so long
                # subtitles wrap gracefully at 65ch.
                "className": "max-w-[65ch] text-sm text-muted-foreground",
            },
        })

    # ── Filter bar + reset chip ───────────────────────────────────────
    filters = maquette.get("filters") or []
    if not isinstance(filters, list) or not filters:
        return nodes

    # Select- and text-kind filters go through FilterBar, NOT a bare Select.
    # This is not cosmetic: `renderSchemaPage` only honours URL params a page
    # DECLARES filterable, and it reads that declaration from FilterBar chip
    # keys (+ "q" when showSearch). A bare Select writes nothing to the URL and
    # its field is never in the allowed set, so the chip filtered nothing.
    bar_children: list[dict] = []
    chips: list[dict] = []
    show_search = False

    for f in filters:
        if not isinstance(f, dict):
            continue
        kind = f.get("kind")
        field_ = f.get("field")
        label = f.get("label")
        if not (isinstance(kind, str) and isinstance(field_, str)
                and isinstance(label, str)):
            continue
        if kind == "select":
            # FilterBar renders "Any" as the cleared state itself, so the
            # options list carries only real values — no "All x" placeholder.
            opts = [
                {"value": o, "label": o}
                for o in (f.get("options") or [])
                if isinstance(o, str) and o.strip()
            ]
            # FilterChip requires >= 1 option. A chip with none offers only
            # "Any", i.e. it filters nothing — drop it rather than ship an
            # invalid node the renderer would reject wholesale.
            if not opts:
                continue
            chips.append({
                "key":          field_,
                "label":        label,
                "options":      opts,
                "defaultValue": "",
            })
        elif kind == "date-range":
            bar_children.append({
                "type": "DateRangePicker",
                "props": {
                    "name":  field_,
                    "label": label,
                },
            })
        elif kind == "text":
            # FilterBar owns one free-text box, bound to "q" — the key the
            # page's filter seam already recognises.
            show_search = True
        # Unknown kinds already dropped at parse time (from_dict).

    # FilterBarNode requires >= 1 chip, so a search-only bar is not
    # expressible — and would filter nothing anyway, since the page's filter
    # seam excludes "q" from dataSource narrowing.
    if chips:
        bar_children.insert(0, {
            "type": "FilterBar",
            "props": {"chips": chips, "showSearch": show_search},
        })

    if bar_children and maquette.get("reset_filters"):
        bar_children.append({
            "type": "Button",
            "props": {
                "label":     "Reset all filters",
                "variant":   "ghost",
                "size":      "sm",
                # Real behaviour, not a data-attribute contract nothing
                # implemented: the library Button clears the query string and
                # fires forge:urlstate so the page re-resolves. Declarative, so
                # the editor exposes it as a toggle.
                "clearsFilters": True,
                "className": "self-end",
            },
        })

    if bar_children:
        nodes.append({
            "type": "Cluster",
            "props": {
                "gap":       "tokens.spacing.3",
                "wrap":      True,
                "align":     "end",
                "className": "border-b border-border/40 pb-4",
            },
            "children": bar_children,
        })

    return nodes


def _build_sections(maquette: dict) -> tuple[list[dict], list[dict]]:
    """Turn a maquette dict into a list of schema section nodes + the
    dataSources they reference. Both lists are ready to slot into a page.
    """
    sections: list[dict] = []
    data_sources: list[dict] = []
    used_source_names: set[str] = set()

    # ── Slice C — section chrome (subtitle + filter bar + reset) ─────
    # Emitted BEFORE any other section so it reads as the page's
    # editorial header, matching the Banking Suite grammar (see
    # docs/superpowers/specs/2026-08-15-widget-anatomy-composition-recipes.md).
    #
    # Composer never invents chrome — it renders exactly what the
    # maquette declared. Missing = no chrome, which is byte-safe with
    # every existing app.
    _chrome_nodes = _build_chrome_nodes(maquette)
    sections.extend(_chrome_nodes)

    # ── Ornament (before-hero placement) ──────────────────────────────
    # Small decorative flourish sprinkled between sections. "before-hero"
    # sits at the very top; other placements are honoured in-line below.
    ornament = maquette.get("ornament")
    _pre_hero_ornament = _build_ornament_node(ornament, placement="before-hero")
    if _pre_hero_ornament is not None:
        sections.append(_pre_hero_ornament)

    # ── Hero ──────────────────────────────────────────────────────────
    # Phase 2 moments layer: kind decides layout. Each variant maps to a
    # different component tree so two same-domain apps don't collapse to
    # the same photo-greeting pattern.
    hero = maquette.get("hero")
    if isinstance(hero, dict):
        _hero_node = _build_hero_node(hero)
        if _hero_node is not None:
            sections.append(_hero_node)

    # ── Empty state (dashboard-scoped) ────────────────────────────────
    # First-run moment when the primary data source has no rows.
    # Composer emits it as IllustratedEmpty at the top of the page —
    # visible only to fresh-install users; downstream data-source
    # binding decides when to reveal it.
    _empty_node = _build_dashboard_empty_state(maquette.get("empty_state"))
    if _empty_node is not None:
        sections.append(_empty_node)

    # ── KPI row ───────────────────────────────────────────────────────
    kpis = maquette.get("kpis") or []
    kpi_children: list[dict] = []
    for i, kpi in enumerate(kpis):
        if not isinstance(kpi, dict):
            continue
        label = kpi.get("label")
        entity = kpi.get("entity")
        op = kpi.get("op")
        if not (label and entity and op):
            continue
        source_name = _unique_name(f"{entity}_{op}_{i}", used_source_names)
        ds_props: dict[str, Any] = {
            "entity": str(entity),
            "op": str(op),
        }
        if kpi.get("field"):
            ds_props["field"] = str(kpi["field"])
        if kpi.get("filter"):
            ds_props["filter"] = str(kpi["filter"])
        data_sources.append({"name": source_name, **ds_props})
        # Renderer's MetricTile schema requires `format` (enum:
        # number|currency|percent|duration). Default "number" — the
        # planner sets a richer value in the maquette when known.
        # trend_window is a maquette hint, not a schema prop; use it
        # to widen the value-source query rather than passing it through.
        fmt = str(kpi.get("format") or "number")
        if fmt not in ("number", "currency", "percent", "duration"):
            fmt = "number"
        tile_props: dict[str, Any] = {
            "label": str(label),
            "value": f"{{{{{source_name}}}}}",
            "format": fmt,
        }

        # ── Slice A / KPI anatomy — breakdown + threshold + extremes ─
        # Every breakdown row and every extremes row gets its own
        # dataSource (op:count/sum/max/min via same engine); MetricTile
        # renders them as sub-lines under the primary value.
        raw_breakdown = kpi.get("breakdown") if isinstance(kpi.get("breakdown"), list) else []
        breakdown_rows: list[dict[str, Any]] = []
        for bi, br in enumerate(raw_breakdown):
            if not isinstance(br, dict):
                continue
            b_label = br.get("label")
            b_entity = br.get("entity")
            b_op = br.get("op")
            if not (b_label and b_entity and b_op):
                continue
            b_source = _unique_name(
                f"{entity}_{op}_{i}_bd{bi}", used_source_names,
            )
            b_ds: dict[str, Any] = {"entity": str(b_entity), "op": str(b_op)}
            if br.get("field"):
                b_ds["field"] = str(br["field"])
            if br.get("filter"):
                b_ds["filter"] = str(br["filter"])
            data_sources.append({"name": b_source, **b_ds})
            breakdown_rows.append({
                "label": str(b_label),
                # String binding — MetricTile is mustache-tolerant on
                # both value + breakdown values, so the renderer resolves
                # {{source}} at render time and formats the numeric
                # result via Intl.NumberFormat.
                "value": f"{{{{{b_source}}}}}",
            })

        # Extremes — max/min companion values derived from the KPI's own
        # entity + field (only for numeric aggregations). Skipped when
        # the KPI has no field to aggregate (e.g. bare count).
        raw_ext = kpi.get("extremes") if isinstance(kpi.get("extremes"), dict) else None
        if raw_ext and kpi.get("field"):
            mx_label = raw_ext.get("max_label") if isinstance(raw_ext.get("max_label"), str) else None
            mn_label = raw_ext.get("min_label") if isinstance(raw_ext.get("min_label"), str) else None
            if mx_label:
                mx_source = _unique_name(
                    f"{entity}_max_{i}", used_source_names,
                )
                data_sources.append({
                    "name": mx_source, "entity": str(entity),
                    "op": "max", "field": str(kpi["field"]),
                })
                breakdown_rows.append({
                    "label": str(mx_label),
                    "value": f"{{{{{mx_source}}}}}",
                })
            if mn_label:
                mn_source = _unique_name(
                    f"{entity}_min_{i}", used_source_names,
                )
                # data-engine ``op`` doesn't have "min" today — approximate
                # with ``op: "avg"`` fallback; the composer's job is to
                # declare intent, and the runtime is free to add real min.
                # TODO(min-op): promote to first-class op in data-engine.
                data_sources.append({
                    "name": mn_source, "entity": str(entity),
                    "op": "max", "field": str(kpi["field"]),
                    "sort": "asc",  # min = max with ascending sort until
                                     # data-engine grows a real min op
                })
                breakdown_rows.append({
                    "label": str(mn_label),
                    "value": f"{{{{{mn_source}}}}}",
                })

        if breakdown_rows:
            tile_props["breakdown"] = breakdown_rows

        # ── threshold ────────────────────────────────────────────────
        raw_thresh = kpi.get("threshold") if isinstance(kpi.get("threshold"), dict) else None
        if raw_thresh:
            th_props: dict[str, Any] = {}
            wa = raw_thresh.get("warn_above")
            ca = raw_thresh.get("critical_above")
            if isinstance(wa, (int, float)) and not isinstance(wa, bool):
                th_props["warnAbove"] = wa
            if isinstance(ca, (int, float)) and not isinstance(ca, bool):
                th_props["criticalAbove"] = ca
            if isinstance(raw_thresh.get("color_on_value"), bool):
                th_props["colorOnValue"] = raw_thresh["color_on_value"]
            if th_props:
                tile_props["threshold"] = th_props

        kpi_children.append({"type": "MetricTile", "props": tile_props})
    if kpi_children:
        sections.append({"type": "Heading",
                         "props": {"content": "Overview", "level": 2}})
        # Responsive Grid adapts columns to KPI count so the row fills
        # the available width instead of leaving a trailing empty
        # column. 4+ KPIs → 4-col at lg (2-col at sm). 3 → 3-col at lg.
        # 2 → 2-col at all sizes ≥ sm. 1 → single wide tile.
        n = len(kpi_children)
        _columns = 4 if n >= 4 else 3 if n == 3 else 2 if n == 2 else 1
        sections.append({
            "type": "Grid",
            "props": {
                "gap": "tokens.spacing.4",
                "columns": _columns,
            },
            "children": kpi_children,
        })
        # Ornament: after-kpis placement
        _kpi_ornament = _build_ornament_node(ornament, placement="after-kpis")
        if _kpi_ornament is not None:
            sections.append(_kpi_ornament)

    # ── Primary chart ─────────────────────────────────────────────────
    pc = maquette.get("primary_chart")
    if isinstance(pc, dict) and pc.get("entity") and pc.get("group_by"):
        chart_name = _unique_name(f"{pc['entity']}_series", used_source_names)
        chart_ds: dict[str, Any] = {
            "entity": str(pc["entity"]),
            "op": "series",
            "groupBy": str(pc["group_by"]),
            "aggregate": str(pc.get("aggregate", "count")),
        }
        if pc.get("aggregate_field"):
            chart_ds["aggregateField"] = str(pc["aggregate_field"])
        if pc.get("window"):
            chart_ds["window"] = str(pc["window"])
        data_sources.append({"name": chart_name, **chart_ds})
        sections.append({"type": "Heading",
                         "props": {"content": str(pc.get("title", "Trends")), "level": 2}})
        # Renderer's Chart schema (packages/schema/nodes/charts.ts):
        #   chartType: enum(line|bar|area|pie|donut|funnel|radar)   REQUIRED
        #   data:      array|string-binding                          REQUIRED
        #   series:    array of {name,dataKey,color?}                REQUIRED
        # The composer's `kind` field maps to `chartType`. The data
        # source resolves to [{label, value}] rows (see resolveSeries
        # runtime), so xKey/dataKey are stable across all series charts.
        kind = str(pc.get("kind", "bar")).lower()
        chart_type = kind if kind in ("line", "bar", "area", "pie", "donut", "funnel", "radar") else "bar"
        chart_props: dict[str, Any] = {
            "chartType": chart_type,
            "data": f"{{{{{chart_name}}}}}",
            "xKey": "label",
            "series": [{"name": str(pc.get("title", "Value")), "dataKey": "value"}],
        }

        # ── Slice A / Chart anatomy — author extra data sources for
        # overlay + pass through view_toggles/encoding/semantic_color
        # verbatim so the renderer can pick them up. All optional; a
        # bare maquette produces the exact same schema as before.
        chart_props["title"] = str(pc.get("title", "Trends"))
        if isinstance(pc.get("help"), str) and pc["help"].strip():
            chart_props["help"] = pc["help"].strip()

        raw_ov = pc.get("overlay") if isinstance(pc.get("overlay"), dict) else None
        if raw_ov and isinstance(raw_ov.get("kind"), str):
            ov_name = _unique_name(
                f"{pc['entity']}_series_overlay", used_source_names,
            )
            ov_ds: dict[str, Any] = {
                "entity":    str(pc["entity"]),
                "op":        "series",
                "groupBy":   str(pc["group_by"]),
                "aggregate": str(raw_ov.get("aggregate", "count")),
            }
            if raw_ov.get("aggregate_field"):
                ov_ds["aggregateField"] = str(raw_ov["aggregate_field"])
            if pc.get("window"):
                ov_ds["window"] = str(pc["window"])
            data_sources.append({"name": ov_name, **ov_ds})
            overlay_props: dict[str, Any] = {
                "chartType": str(raw_ov["kind"]),
                "data":      f"{{{{{ov_name}}}}}",
                "series":    [{"name": str(pc.get("title", "Value") + " (overlay)"),
                                "dataKey": "value"}],
            }
            if raw_ov.get("curve") in ("straight", "smooth"):
                overlay_props["curve"] = raw_ov["curve"]
            chart_props["overlay"] = overlay_props

        raw_vt = pc.get("view_toggles")
        if isinstance(raw_vt, list) and raw_vt:
            vt_out = []
            for t in raw_vt:
                if not (isinstance(t, dict) and isinstance(t.get("label"), str) and t["label"].strip()):
                    continue
                mod = t.get("modifier") if isinstance(t.get("modifier"), dict) else {}
                entry: dict = {"label": t["label"].strip(), "modifier": dict(mod)}
                if t.get("default"):
                    entry["default"] = True
                vt_out.append(entry)
            if vt_out:
                chart_props["viewToggles"] = vt_out

        raw_enc = pc.get("encoding") if isinstance(pc.get("encoding"), dict) else None
        if raw_enc:
            enc_out: dict = {}
            if raw_enc.get("leaderboard"):     enc_out["leaderboard"] = True
            if raw_enc.get("stacked"):         enc_out["stacked"] = True
            if raw_enc.get("sorted") in ("asc", "desc"):
                enc_out["sorted"] = raw_enc["sorted"]
            if isinstance(raw_enc.get("top_n"), int) and raw_enc["top_n"] > 0:
                enc_out["topN"] = raw_enc["top_n"]
            if raw_enc.get("value_labels"):    enc_out["valueLabels"] = True
            if enc_out:
                chart_props["encoding"] = enc_out

        raw_sc = pc.get("semantic_color")
        if (isinstance(raw_sc, dict) and raw_sc.get("by") == "field"
                and isinstance(raw_sc.get("field"), str)
                and isinstance(raw_sc.get("map"), dict) and raw_sc["map"]):
            cleaned = {k: v for k, v in raw_sc["map"].items()
                       if isinstance(k, str) and isinstance(v, str)}
            if cleaned:
                chart_props["semanticColor"] = {
                    "by": "field", "field": raw_sc["field"], "map": cleaned,
                }

        sections.append({"type": "Chart", "props": chart_props})
        # Ornament: after-chart placement
        _chart_ornament = _build_ornament_node(ornament, placement="after-chart")
        if _chart_ornament is not None:
            sections.append(_chart_ornament)

    # ── Activity feed ─────────────────────────────────────────────────
    act = maquette.get("activity")
    if isinstance(act, dict) and act.get("entity"):
        act_name = _unique_name(f"{act['entity']}_recent", used_source_names)
        limit = act.get("limit") if isinstance(act.get("limit"), int) else 5
        order_by = act.get("order_by", "createdAt")
        data_sources.append({
            "name": act_name,
            "entity": str(act["entity"]),
            "op": "list",
            "orderBy": str(order_by),
            "orderDir": "desc",
            "limit": int(limit),
        })
        sections.append({"type": "Heading",
                         "props": {"content": str(act.get("title", "Recent activity")), "level": 2}})
        sections.append({
            "type": "ActivityFeed",
            "props": {
                "dataSource": f"{{{{{act_name}}}}}",
            },
        })

    # ── Footer (before-footer ornament first, then footer band) ──────
    _pre_footer_ornament = _build_ornament_node(ornament, placement="before-footer")
    if _pre_footer_ornament is not None:
        sections.append(_pre_footer_ornament)
    _footer_node = _build_dashboard_footer(maquette.get("footer"))
    if _footer_node is not None:
        sections.append(_footer_node)

    return sections, data_sources


# ─────────────────────────── slot helpers ──────────────────────────────


def _build_dashboard_empty_state(empty: Any) -> Optional[dict]:
    """Render an `IllustratedEmpty` for the dashboard's first-run moment.

    Returns None when the slot is unset or missing a headline. The
    composer keeps this ABOVE the data-bound sections; downstream
    binding decides visibility via `hideWhenAny` on the dataSource.
    """
    if not isinstance(empty, dict):
        return None
    headline = empty.get("headline")
    if not (isinstance(headline, str) and headline.strip()):
        return None
    props: dict[str, Any] = {
        "illustration": empty.get("illustration") or "welcome-mat",
        "headline": headline.strip(),
        "data-slot": "dashboard-empty-state",
    }
    for k in ("subhead", "cta_label", "cta_action"):
        v = empty.get(k)
        if isinstance(v, str) and v.strip():
            props[k.replace("_", "-")] = v.strip()
    return {"type": "IllustratedEmpty", "props": props}


def _build_ornament_node(ornament: Any, *, placement: str) -> Optional[dict]:
    """Emit a small decorative flourish, or None when the ornament isn't
    for this placement.

    Ornament kinds:
      * ``eyebrow-line`` — thin accent line (Divider variant).
      * ``corner-illustration`` — tiny illustration (IllustratedEmpty w/o headline).
      * ``section-divider`` — decorative Divider between sections.
      * ``accent-badge`` — small Badge to add texture.
    """
    if not isinstance(ornament, dict):
        return None
    if ornament.get("placement") != placement:
        return None
    kind = ornament.get("kind")
    if not isinstance(kind, str):
        return None

    if kind == "eyebrow-line":
        return {
            "type": "Divider",
            "props": {"variant": "eyebrow", "data-ornament": "eyebrow-line",
                      "data-placement": placement},
        }
    if kind == "section-divider":
        return {
            "type": "Divider",
            "props": {"variant": "decorative", "data-ornament": "section-divider",
                      "data-placement": placement},
        }
    if kind == "accent-badge":
        return {
            "type": "Badge",
            "props": {"content": ornament.get("content") or "•",
                      "tone": "accent", "data-ornament": "accent-badge",
                      "data-placement": placement},
        }
    if kind == "corner-illustration":
        return {
            "type": "IllustratedEmpty",
            "props": {"illustration": ornament.get("illustration") or "sunlit-window",
                      "headline": "", "size": "corner",
                      "data-ornament": "corner-illustration",
                      "data-placement": placement},
        }
    return None


def _build_dashboard_footer(footer: Any) -> Optional[dict]:
    """Render the dashboard footer band."""
    if not isinstance(footer, dict):
        return None
    kind = footer.get("kind")
    if not (isinstance(kind, str) and kind in (
            "support-links", "attribution", "next-steps", "insight")):
        return None
    content = footer.get("content") if isinstance(footer.get("content"), str) else None

    if kind == "support-links":
        return {
            "type": "Row",
            "props": {"justify": "center", "align": "center", "gap": "tokens.spacing.4",
                      "data-slot": "dashboard-footer", "data-footer-kind": "support-links"},
            "children": [
                {"type": "Text",
                 "props": {"content": content or "Need help? Contact support.",
                           "variant": "caption"}},
            ],
        }
    if kind == "attribution":
        return {
            "type": "Row",
            "props": {"justify": "center", "align": "center",
                      "data-slot": "dashboard-footer", "data-footer-kind": "attribution"},
            "children": [
                {"type": "Text",
                 "props": {"content": content or "", "variant": "caption"}},
            ],
        }
    if kind == "next-steps":
        return {
            "type": "Card",
            "props": {"padding": "tokens.spacing.6",
                      "data-slot": "dashboard-footer", "data-footer-kind": "next-steps"},
            "children": [
                {"type": "Heading",
                 "props": {"content": "What's next", "level": 3}},
                {"type": "Text", "props": {"content": content or ""}},
            ],
        }
    # insight
    return {
        "type": "Card",
        "props": {"padding": "tokens.spacing.4",
                  "data-slot": "dashboard-footer", "data-footer-kind": "insight"},
        "children": [
            {"type": "Text", "props": {"content": content or ""}},
        ],
    }


def _build_hero_node(hero: dict) -> Optional[dict]:
    """Build a hero section based on the maquette's `kind` field.

    Phase 2 moments layer: each hero kind emits a different component
    tree so two same-domain apps don't collapse to the same
    photo-greeting pattern.

    Returns None when the hero shape can't be honored (missing required
    field for its kind) — the composer skips the slot rather than emit
    a broken node.

    Kind → emitter:
      * ``photo-greeting`` (default) — legacy `Hero` component with
        `photoSubject` picked up by ``post_emit_photo_injector``.
      * ``personalised-greeting`` — text-only `Hero` with no photo. The
        greeting typically embeds `{firstName}` for the renderer to
        resolve from the session.
      * ``editorial-quote`` — centred pull-quote as `Heading` +
        attribution `Text`, wrapped in a padded `Card` so it reads
        as a moment, not a caption.
      * ``kpi-strip`` — small headline `Heading` + a marker attribute
        the KPI-row emitter can key off to promote the row into the
        hero band. Downstream composers can style differently based
        on the `data-hero-kind` attribute.
      * ``balance-rings`` — headline + marker for the composer to
        emit a `SplitArc`/`Gauge` widget over the primary balance
        entity. When no balance entity is available the greeting-only
        fallback still ships.
    """
    kind = hero.get("kind") if isinstance(hero.get("kind"), str) else "photo-greeting"
    greeting = str(hero.get("greeting") or "")
    subhead = str(hero.get("subhead") or "")

    if kind == "editorial-quote":
        quote = str(hero.get("quote") or "")
        if not quote:
            return None
        attribution = str(hero.get("attribution") or "")
        children: list[dict] = [
            {"type": "Heading", "props": {
                "content": quote, "level": 2, "align": "center",
            }},
        ]
        if attribution:
            children.append({
                "type": "Text",
                "props": {"content": attribution, "align": "center", "variant": "caption"},
            })
        return {
            "type": "Card",
            "props": {
                "padding": "tokens.spacing.10",
                "data-hero-kind": "editorial-quote",
            },
            "children": children,
        }

    if kind == "personalised-greeting":
        if not greeting:
            return None
        return {
            "type": "Hero",
            "props": {
                "title": greeting,
                "subtitle": subhead,
                # No photo — personalised greeting reads better as text-first.
                "photoSubject": "",
                "data-hero-kind": "personalised-greeting",
            },
        }

    if kind == "kpi-strip":
        if not greeting:
            return None
        return {
            "type": "Hero",
            "props": {
                "title": greeting,
                "subtitle": subhead,
                "photoSubject": "",
                # Marker for downstream KPI-row emitter — it can style
                # the row differently when the hero promoted it.
                "data-hero-kind": "kpi-strip",
            },
        }

    if kind == "balance-rings":
        if not greeting:
            return None
        return {
            "type": "Hero",
            "props": {
                "title": greeting,
                "subtitle": subhead,
                "photoSubject": "",
                "data-hero-kind": "balance-rings",
            },
        }

    # Default: legacy photo-greeting. Preserves pre-Phase-2 behaviour
    # exactly (including the post_emit_photo_injector wire-up).
    if not greeting:
        return None
    return {
        "type": "Hero",
        "props": {
            "title": greeting,
            "subtitle": subhead,
            "photoSubject": str(hero.get("photo_subject") or ""),
            "data-hero-kind": "photo-greeting",
        },
    }


def _unique_name(base: str, used: set[str]) -> str:
    """Slug + de-dupe a dataSource name."""
    slug = "".join(c if c.isalnum() or c == "_" else "_" for c in base).strip("_") or "ds"
    name = slug
    i = 2
    while name in used:
        name = f"{slug}_{i}"
        i += 1
    used.add(name)
    return name
